"""
Southbound Network Controller for TinyLEO Toolkit
This module implements the southbound network controller for managing satellite and ground station networks.
It includes functionalities for:
- Managing containers and their lifecycle (creation, initialization, and cleanup).
- Initializing and updating network topology.
- Managing remote machines and their configurations.
- Handling link failures.
- Deploying SRv6 agents for data plane operations.
- Supporting network testing tools like ping, iperf, and traceroute.
"""

import time
import json
import threading
import os
import shlex
import sys
from concurrent.futures import Future, ThreadPoolExecutor
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from southbound.sn_utils import *
from failure_recovery_mpc import MPCFaultHandler
from sn_orchestrator_mpc import *


ASSIGN_FILENAME = 'assign.json'
PID_FILENAME = 'container_pid.txt'
NOT_ASSIGNED = 'NA'


def _start_result_thread(function, *args):
    """Run a command in a daemon thread and expose its exception via Future."""
    future = Future()

    def run():
        if not future.set_running_or_notify_cancel():
            return
        try:
            future.set_result(function(*args))
        except BaseException as exc:
            future.set_exception(exc)

    threading.Thread(target=run, daemon=True).start()
    return future

class RemoteController():
    """
    A class to manage containers on remote machines for the TinyLEO Toolkit.
    This class handles the initialization, configuration, and management of
    satellite and ground station networks, including container lifecycle,
    topology updates, fault testing, and recovery.

    Attributes:
        gs_lat_long (list): List of ground station latitude and longitude coordinates.
        link_style (str): The style of inter-satellite links (e.g., dynamic or static).
        link_policy (str): The policy for link management.
        duration (int): The total duration of the simulation.
        sat_bandwidth (int): Bandwidth of inter-satellite links.
        sat_ground_bandwidth (int): Bandwidth of satellite-to-ground links.
        sat_loss (float): Packet loss rate for inter-satellite links.
        sat_ground_loss (float): Packet loss rate for satellite-to-ground links.
        antenna_number (int): Number of antennas per ground station.
        elevation (float): Elevation angle for antennas.
        configuration_dir (str): Directory path for configuration files.
        experiment_name (str): Name of the experiment.
        gs_dirname (str): Directory name for ground station data.
        GS_cell (dict): Mapping of ground station cells.
        local_dir (str): Local directory for experiment data.
        machine_lst (list): List of remote machines for the simulation.
        data_plane_dir (str): Directory for data plane geographic srv6 anycast.
    """

    def __init__(
        self,
        configuration_file_path,
        GS_lat_long,
        GS_cell,
        topology_predictor=None,
        topology_generator=None,
    ):
        """
        Initializes the RemoteController instance with the given arguments.

        Args:
            configuration_file_path (str): Path to the configuration file.
            GS_lat_long (list): List of ground station latitude and longitude coordinates.
            GS_cell (dict): Mapping of ground station cells.
        """
        sn_args = sn_load_file(configuration_file_path)
        self.gs_lat_long = GS_lat_long
        self.link_style = sn_args.link_style
        self.link_policy = sn_args.link_policy
        self.start_epoch = sn_args.start_epoch
        self.num_epochs = sn_args.num_epochs
        self.duration = self.num_epochs
        self.topology_update_interval_s = sn_args.topology_update_interval_s
        self.execution_mode = sn_args.execution_mode
        self.enable_failure_recovery = sn_args.enable_failure_recovery
        self.num_processes = sn_args.num_processes
        self.remote_python = sn_args.remote_python
        self.failure_controller_endpoint = sn_args.failure_controller_endpoint
        self.satellite_file = sn_args.satellite_file
        self.traffic_matrix_file = sn_args.traffic_matrix_file
        self.grid_satellites_file = sn_args.grid_satellites_file
        self.block_positions_file = sn_args.block_positions_file
        self.sat_bandwidth = sn_args.sat_bandwidth
        self.sat_ground_bandwidth = sn_args.sat_ground_bandwidth
        self.sat_loss = sn_args.sat_loss
        self.sat_ground_loss = sn_args.sat_ground_loss
        self.antenna_number = sn_args.antenna_number
        self.elevation = sn_args.antenna_elevation
        self.configuration_dir = os.path.abspath(os.path.dirname(configuration_file_path))
        self.experiment_name = sn_args.cons_name+'-'+ sn_args.link_style +'-'+ sn_args.link_policy
        self.gs_dirname = 'GS-'+ str(len(self.gs_lat_long))
        self.GS_cell = GS_cell
        self.local_dir = os.path.abspath(os.path.join(self.configuration_dir,'..', self.experiment_name))
        self.machine_lst = sn_args.machine_lst
        self.topo_dir = sn_args.topo_dir
        self._topology_predictor = topology_predictor or predict_all_topologies
        self._topology_generator = topology_generator or generate_topology_for_timestamp
        self.data_plane_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..','geographic_srv6_anycast'))

    def _predict_topologies(self):
        return self._topology_predictor(
            duration=self.num_epochs,
            satellite_file=self.satellite_file,
            traffic_matrix_file=self.traffic_matrix_file,
            grid_satellites_file=self.grid_satellites_file,
            result_output_dir=self.local_dir,
            num_processes=self.num_processes,
            start_epoch=self.start_epoch,
        )

    def _generate_topology_for_timestamp(self, timestamp):
        return self._topology_generator(
            timestamp=timestamp,
            satellite_file=self.satellite_file,
            block_positions_file=self.block_positions_file,
            traffic_matrix_file=self.traffic_matrix_file,
            grid_satellites_file=self.grid_satellites_file,
            output_dir=self.local_dir,
            num_processes=self.num_processes,
            start_epoch=self.start_epoch,
            num_epochs=self.num_epochs,
        )
    
    def init_remote_machine(self):
        """
        Initializes the simulation environment in remote machines.
        """
        # Predict and generate topology data for the simulation
        print('Predict topo data')
        self._predict_topologies()
        # Initialize files for containers and topology
        self._init_tinyleo_topology()
        for shell_id, shell in enumerate(self.shell_lst):
            shell['name'] = f"shell{shell_id}"
        self._init_local()
        sat_names_shell,self.all_link_states,self.link_count = init_tinyleo_links(self.local_dir,self.shell_lst,self.gs_dirname)
        (self.remote_lst,self.sat_mid_dict,self.gs_mid_dict) = self._assign_remote(sat_names_shell, self.machine_lst)

    def start_link_faliure_server(self):
        """
        Starts a gRPC server to handle link failure events.
        """
        self.link_failure_server = link_faliure_server(self)
        def server_wait():
            self.link_failure_server.wait_for_termination()
        t = threading.Thread(target=server_wait, daemon=True)
        t.start()

    def handle_link_failure(self, sat1, sat2):
        """
        Handles a link failure between two satellites and updates the network topology accordingly.

        Args:
            sat1 (str): Name of the first satellite involved in the link failure.
            sat2 (str): Name of the second satellite involved in the link failure.

        Returns:
            list: A list of satellites whose states were updated.
        """
        failed_link = [sat1, sat2]
        print(f"Link failure between {sat1} and {sat2}")
        mpc = MPCFaultHandler(
            topology_dir=self.local_dir,
            satellite_file=self.satellite_file,
            grid_satellites_file=self.grid_satellites_file,
            runtime_epoch=self.ts,
            source_epoch=self.start_epoch + self.ts,
        )
        result = mpc.handle_link_failure(get_satellite_id(sat1), get_satellite_id(sat2))
        update_sats = set()
        if not result or 'replacement_info' not in result:
            raise RuntimeError("failure recovery MPC returned no replacement identity")
        remove_sat = get_satellite_name(result['replacement_info']['removed_satellite'])
        replacement_sat = get_satellite_name(result['replacement_info']['replacement_satellite'])
        print('remove sat',remove_sat,'replace sat',replacement_sat)
        update_sats.add(remove_sat)
        update_sats.add(replacement_sat)
        sat1 = replacement_sat
        # isls
        for sat2 in self.all_node_states[remove_sat]['isls']:
            sat1_ip,sat2_ip = isl_addr6_ips(sat1,sat2)
            sat1_ip,sat2_ip = sat1_ip.split('/')[0],sat2_ip.split('/')[0]
            sat1_mac,sat2_mac = isl_mac(sat1,sat2)
            delay = compute_delay_from_cbf(self.all_node_states[sat1]['position']['cbf'],self.all_node_states[sat2]['position']['cbf'])
            self.all_node_states[sat1]['isls'][sat2] = [sat2_ip, sat2_mac, delay]
            self.all_node_states[sat2]['isls'].pop(remove_sat)
            self.all_node_states[sat2]['isls'][sat1] = [sat1_ip, sat1_mac, delay]
        self.all_node_states[remove_sat]['isls'] = {}

        # cell_ring
        new_cell_ring = self.all_node_states[remove_sat]['cell_ring']
        for i in range(len(new_cell_ring)):
            if new_cell_ring[i] == remove_sat:
                new_cell_ring[i] = replacement_sat
        for sat in new_cell_ring:
            update_sats.add(sat)
            self.all_node_states[sat]['cell_ring'] = new_cell_ring
        self.all_node_states[remove_sat]['cell_ring'] = []

        # sat_cell
        self.all_node_states[replacement_sat]['sat_cell'] = self.all_node_states[remove_sat]['sat_cell']
        self.all_node_states[remove_sat]['sat_cell'] = []

        # intra_cell_isls
        if self.all_node_states[remove_sat]['inter_cell_isls']!={}:
            self.all_node_states[replacement_sat]['inter_cell_isls'] = self.all_node_states[remove_sat]['inter_cell_isls']
            self.all_node_states[remove_sat]['inter_cell_isls'] = {}
            near_sat = self.all_node_states[replacement_sat]['inter_cell_isls']['near_sat']
            sat_cell = self.all_node_states[replacement_sat]['sat_cell']
            self.all_node_states[near_sat]['inter_cell_isls']['near_sat'] = replacement_sat
            self.all_node_states[near_sat]['inter_cell_isls']['near_cell'] = sat_cell
        with open(os.path.join(self.local_dir,'all_node_states', f'{self.ts}.json'), 'w') as f:
            json.dump(self.all_node_states, f, indent=4)
        f_update = open(os.path.join(self.local_dir,'shell0','isl',f'{self.ts}.txt'), 'w')
        
        for sat1 in update_sats:
            f_update.write(f"{sat1}|")
            f_update.write("|")
            f_update.write("|")
            add_lst = []
            for sat2 in self.all_node_states[sat1]['isls']:
                delay = self.all_node_states[sat1]['isls'][sat2][2]
                # print(sat1,sat2,delay)
                if int(sat1.split('SAT')[-1])<int(sat2.split('SAT')[-1]):
                    key = f"{sat1}-{sat2}"
                else:
                    key = f"{sat2}-{sat1}"
                if key not in self.all_link_states:
                    self.all_link_states[key] = delay
                    add_lst.append(f"{sat2},{delay:.2f},{self.link_count}")
                    self.link_count += 1
            f_update.write(' '.join(add_lst))
            f_update.write('\n')
        f_update.close()
        for remote in self.remote_lst:
            remote.upload_failure_recovery_file(self.ts)
        print('update sats:', len(update_sats), update_sats)
        return {
            'failed_link': failed_link,
            'removed_satellite': remove_sat,
            'replacement_satellite': replacement_sat,
            'updated_satellites': sorted(update_sats),
            'epoch': self.ts,
        }

    def _init_tinyleo_topology(self):
        """
        Initializes the TinyLEO topology by loading the predicted inter-satellite
        link positions from a JSON file.
        """
        self.shell_lst = []
        topo_path = os.path.join(self.local_dir,'predict_isl_position_all.json')
        with open(topo_path, 'r') as f:
            tinyleo_shell = json.load(f)
        self.shell_lst.append(tinyleo_shell)

    def update_tinyleo_topology(self,ts):
        """
        Updates the TinyLEO topology for a specific timestamp.

        Args:
            ts (int): The timestamp for which the topology should be updated.
        """
        self.ts = ts
        self._generate_topology_for_timestamp(self.ts)

        self.shell_lst = []
        topo_path = os.path.join(self.local_dir,'all_isl_positions',f"{ts}.json")
        with open(topo_path, 'r') as f:
            tinyleo_topo = json.load(f)
        tinyleo_topo['name'] = "shell0"
        self.shell_lst.append(tinyleo_topo)
        isl_sats_path = os.path.join(self.local_dir, 'sat_cells', f"{ts}.json")
        with open(isl_sats_path, 'r') as f:
            self.isl_sats = json.load(f)
        inter_cell_isls = os.path.join(self.local_dir, 'inter_cell_isls', f"{ts}.json")
        with open(inter_cell_isls, 'r') as f:
            self.inter_cell_isls = json.load(f)
        self.all_node_states = {}
        self.link_count = update_tinyleo_link(self.local_dir,ts,self.all_link_states,self.shell_lst,self.gs_lat_long,
                                              self.antenna_number,self.isl_sats,self.GS_cell,self.link_count,self.geopraphic_routing_policy,
                                              self.inter_cell_isls,self.all_node_states)
        self.update_remote_topology()
        
    def update_remote_topology(self):
        """
        Updates the network topology on all remote machines for a specific timestamp.

        Args:
            ts (int): The timestamp for which the topology should be updated.
        """
        print(f"Update networks at t {self.ts}...")
        update_start = time.time()
        with ThreadPoolExecutor(max_workers=max(1, len(self.remote_lst))) as pool:
            list(
                pool.map(
                    lambda remote: remote.update_network(
                        self.ts,
                        self.sat_bandwidth,
                        self.sat_loss,
                        self.sat_ground_bandwidth,
                        self.sat_ground_loss,
                    ),
                    self.remote_lst,
                )
            )
        end = time.time()
        print(end-update_start, "s for network update\n")

    def tinyleo_fault_test(self):
        """
        Performs a fault test on the network by simulating link failures.
        """
        print(f"fault test ...")
        update_start = time.time()
        candidates = []
        for sat1 in sorted(self.all_node_states):
            remote = self.nodes.get(sat1)
            if remote is None:
                continue
            for sat2 in sorted(self.all_node_states[sat1].get('isls', {})):
                if sat1 >= sat2 or self.nodes.get(sat2) is not remote:
                    continue
                candidates.append((sat1, sat2, remote))
        if not candidates:
            raise RuntimeError(
                "no deterministic same-machine ISL is available for failure injection"
            )
        sat1, sat2, remote = candidates[0]
        acknowledgement = remote.fault_test(
            self.ts,
            self.sat_bandwidth,
            self.sat_loss,
            self.sat_ground_bandwidth,
            self.sat_ground_loss,
            (sat1, sat2),
        )
        if not isinstance(acknowledgement, dict):
            raise RuntimeError("remote fault command returned no acknowledgement")
        if acknowledgement.get('failed_link') != [sat1, sat2]:
            raise RuntimeError(
                "remote fault acknowledgement does not match requested ISL"
            )
        end = time.time()
        print(end-update_start, "s for fault test\n")
        return acknowledgement

    def deploy_tinyleo_srv6_agent(self):
        """
        Deploy the SRv6 agent on all remote machines for data plane operations.
        """
        print(f"Deploy srv6 agent...")
        update_start = time.time()
        with ThreadPoolExecutor(max_workers=max(1, len(self.remote_lst))) as pool:
            acknowledgements = list(
                pool.map(
                    lambda remote: remote.deploy_tinyleo_srv6_agent(),
                    self.remote_lst,
                )
            )
        remote_ids = set()
        for acknowledgement in acknowledgements:
            if not isinstance(acknowledgement, dict):
                raise RuntimeError("SRv6 deployment returned no acknowledgement")
            remote_id = acknowledgement.get('remote_id')
            if (
                isinstance(remote_id, bool)
                or not isinstance(remote_id, int)
                or remote_id < 0
                or remote_id in remote_ids
            ):
                raise RuntimeError("SRv6 deployment remote identity is invalid")
            remote_ids.add(remote_id)
            expected_count = acknowledgement.get('expected_count', 0)
            agents = acknowledgement.get('agents')
            if (
                expected_count <= 0
                or acknowledgement.get('started_count')
                != expected_count
                or not isinstance(agents, list)
                or len(agents) != expected_count
            ):
                raise RuntimeError("SRv6 deployment did not start every agent")
            namespace_pids = set()
            for agent in agents:
                namespace_pid = (
                    agent.get('namespace_pid')
                    if isinstance(agent, dict)
                    else None
                )
                if (
                    isinstance(namespace_pid, bool)
                    or not isinstance(namespace_pid, int)
                    or namespace_pid <= 0
                ):
                    raise RuntimeError("SRv6 namespace PID is invalid")
                if namespace_pid in namespace_pids:
                    raise RuntimeError(
                        "SRv6 acknowledgement has duplicate namespace PID"
                    )
                namespace_pids.add(namespace_pid)
        if remote_ids != {remote.id for remote in self.remote_lst}:
            raise RuntimeError("SRv6 deployment acknowledgements are incomplete")
        end = time.time()
        print(end-update_start, "s for srv6 agent deploy\n")
        return {'remote_acknowledgements': acknowledgements}

    def _init_local(self):
        """
        Prepares the local directory structure and configuration files for the simulation.
        """
        for txt_file in glob.glob(os.path.join(self.local_dir, '*.txt')):
            os.remove(txt_file)
        for shell in self.shell_lst:
            os.makedirs(os.path.join(self.local_dir, shell['name']), exist_ok=True)
        os.makedirs(os.path.join(self.local_dir, self.gs_dirname), exist_ok=True)
        os.makedirs(os.path.join(self.local_dir,'result'), exist_ok=True)
        os.makedirs(os.path.join(self.local_dir,'all_node_states'), exist_ok=True)
        with open(os.path.join(self.configuration_dir, 'geopraphic_routing_policy.json')) as f:
            self.geopraphic_routing_policy = json.load(f)
        with open(self.block_positions_file) as f:
            self.block_positions = json.load(f)

    def _assign_remote(self, sat_names_shell, machine_lst):
        """
        Assigns satellites and ground stations to remote machines for simulation.

        Args:
            sat_names_shell (list): List of satellite names grouped by shell.
            machine_lst (list): List of remote machine configurations.

        Returns:
            tuple: A tuple containing:
                - remote_lst (list): List of RemoteMachine instances.
                - sat_mid_dict (dict): Mapping of satellite names to machine IDs.
                - gs_mid_dict (dict): Mapping of ground station names to machine IDs.
        """
        assert len(sat_names_shell) == len(self.shell_lst)

        # TODO: better partition
        if len(sat_names_shell) * 2 <= len(machine_lst):
            # need intra-shell partition
            machine_per_shell = len(machine_lst) // len(sat_names_shell)
            raise NotImplementedError
        else:
            # only divide shell
            shell_per_machine = len(self.shell_lst) // len(machine_lst)
            remainder = len(sat_names_shell) % len(machine_lst)

            shell_id = 0
            sat_mid_dict_shell = []
            assigned_shell_lst = []
            for i, remote in enumerate(machine_lst):
                shell_num = shell_per_machine
                if i < remainder:
                    shell_num += 1
                assigned_shells = [
                    (self.shell_lst[j]['name'], sat_names_shell[j])
                      for j in range(shell_id, shell_id + shell_num)
                ]
                # all satellites of a shell assigned to a single machine
                for shell_name, sat_names in assigned_shells:
                    sat_mid_dict = {}
                    for sat_name in sat_names:
                        sat_mid_dict[sat_name] = i
                    sat_mid_dict_shell.append(sat_mid_dict)
                assigned_shell_lst.append(assigned_shells)
                shell_id += shell_num
            gs_mid_dict = {}

            for gs_id,_ in enumerate(self.gs_lat_long):
                gs_name = get_gs_name(gs_id)
                gs_mid_dict[gs_name] = 0

            ip_lst = [remote['IP'] for remote in machine_lst]
            assign_obj = {
                'sat_mid_shell': sat_mid_dict_shell,
                'gs_mid': gs_mid_dict,
                'ip': ip_lst,
            }
            with open(os.path.join(self.local_dir, ASSIGN_FILENAME), 'w') as f:
                json.dump(assign_obj, f)

        remote_lst = []
        for i, remote in enumerate(machine_lst):
            remote_lst.append(RemoteMachine(
                id=i,
                host=remote['IP'],
                port=remote['port'],
                username=remote['username'],
                password=remote.get('password'),
                shell_lst=assigned_shell_lst[i],
                experiment_name=self.experiment_name,
                local_dir=self.local_dir,
                gs_dirname=self.gs_dirname if i in gs_mid_dict.values() else None,
                key_filename=remote.get('key_filename'),
                remote_python=self.remote_python,
                failure_controller_endpoint=self.failure_controller_endpoint,
                )
            )
        return remote_lst, sat_mid_dict, gs_mid_dict

    def create_nodes(self):
        """
        Initializes all simulation nodes (e.g., satellites and ground stations).
        """
        print('Initializing nodes ...')
        begin = time.time()
        for remote in self.remote_lst:
            remote.init_nodes()
        print("Node initialization:", time.time() - begin, "s consumed.\n")
        self._load_node_map()

    def node_map(self):
        """
        Retrieves the mapping of nodes to their respective remote machines.

        Returns:
            dict: A dictionary mapping node names to RemoteMachine instances.
        """
        if hasattr(self, 'nodes'):
            return self.nodes
        self._load_node_map()
        return self.nodes

    def _load_node_map(self):
        """
        Loads the mapping of nodes to their respective remote machines.
        """
        self.nodes = {}
        self.undamaged_lst = list()
        self.total_sat_lst = list()
        for remote in self.remote_lst:
            for node in remote.get_nodes():
                if node.startswith('Error'):
                    print(node)
                    exit(1)
                if not node.startswith('GS'):
                    self.undamaged_lst.append(node)
                    self.total_sat_lst.append(node)
                self.nodes[node.strip()] = remote

    def create_links(self):
        """
        Initializes network links between nodes in the simulation.
        """
        print('Initializing links ...')
        begin = time.time()
        with ThreadPoolExecutor(max_workers=max(1, len(self.remote_lst))) as pool:
            list(
                pool.map(
                    lambda remote: remote.init_network(
                        self.sat_bandwidth,
                        self.sat_loss,
                        self.sat_ground_bandwidth,
                        self.sat_ground_loss,
                    ),
                    self.remote_lst,
                )
            )
        print("Link initialization:", time.time() - begin, 's consumed.\n')

    def set_ping(self, src, dst, filename):
        """
        Sets up a ping test between two nodes.

        Args:
            src (str): Source node name.
            dst (str): Destination node name.
            filename (str): Name of the file to save the ping results.
        """
        node_map = self.node_map()
        machine = node_map[src]
        return machine.ping_async(
            os.path.join(self.local_dir,'result',f'ping-{filename}.txt'),
            src, dst
        )

    def set_iperf(self, src, dst, filename):
        """
        Sets up an iperf test between two nodes.

        Args:
            src (str): Source node name.
            dst (str): Destination node name.
            filename (str): Name of the file to save the iperf results.
        """
        node_map = self.node_map()
        machine = node_map[src]
        return machine.iperf_async(
            os.path.join(self.local_dir,'result', f'iperf-{filename}.txt'),
            src, dst
        )

    def set_traceroute(self, src, dst, filename):
        """
        Sets up a traceroute test between two nodes.

        Args:
            src (str): Source node name.
            dst (str): Destination node name.
            filename (str): Name of the file to save the traceroute results.
        """
        node_map = self.node_map()
        machine = node_map[src]
        return machine.traceroute_async(
            os.path.join(self.local_dir,'result', f'traceroute-{filename}.txt'),
            src, dst
        )

    def get_pid_map(self):
        """
        Retrieves the mapping of container names to their process IDs.

        Returns:
            dict: A dictionary mapping container names to process IDs.
        """
        pid_map_file = os.path.join(self.local_dir, PID_FILENAME)
        _pid_map = {}
        if not os.path.exists(pid_map_file):
            print('Error: container index file not found, please create nodes')
            exit(1)
        with open(pid_map_file, 'r') as f:
            for line in f:
                if len(line) == 0 or line.isspace():
                    continue
                for name_pid in line.strip().split():
                    if name_pid == NOT_ASSIGNED:
                        continue
                    name_pid = name_pid.split(':')
                    _pid_map[name_pid[0]] = name_pid[1]
        return _pid_map
    
    def clean(self):
        """
        Cleans up the simulation environment by removing containers and links.
        """
        print("Removing containers and links...")
        for remote in self.remote_lst:
            remote.clean()
        print("All containers and links remoted.")

class RemoteMachine:
    """
    A class to manage remote machines in the TinyLEO simulation environment.
    This class handles the initialization, configuration, and management of
    remote machines, including uploading necessary files, initializing nodes,
    and managing network configurations.

    Attributes:
        id (int): Unique identifier for the remote machine.
        shell_lst (list): List of satellite shells assigned to this machine.
        local_dir (str): Local directory for storing simulation data.
        gs_dirname (str): Directory name for ground station data.
        ssh (paramiko.SSHClient): SSH client for remote command execution.
        sftp (paramiko.SFTPClient): SFTP client for file transfers.
        dir (str): Remote directory for storing simulation files.
    """

    def __init__(self, id, host, port, username, password=None,
                 shell_lst=None, experiment_name=None, local_dir=None,
                 gs_dirname=None, key_filename=None, remote_python='python3',
                 failure_controller_endpoint='101.6.21.12:50051'):
        """
        Initializes the RemoteMachine instance and sets up the remote environment.

        Args:
            id (int): Unique identifier for the remote machine.
            host (str): Hostname or IP address of the remote machine.
            port (int): SSH port for the remote machine.
            username (str): SSH username.
            password (str): SSH password.
            shell_lst (list): List of satellite shells assigned to this machine.
            experiment_name (str): Name of the experiment.
            local_dir (str): Local directory for storing simulation data.
            gs_dirname (str): Directory name for ground station data.
        """
        self.id = id
        self.shell_lst = shell_lst
        self.local_dir = local_dir
        self.gs_dirname = gs_dirname
        self.remote_python = remote_python
        self.failure_controller_endpoint = failure_controller_endpoint
        self.ssh, self.sftp = sn_connect_remote(
            host = host,
            port = port,
            username = username,
            password = password,
            key_filename = key_filename,
        )
        experiment_component = shlex.quote(experiment_name)
        sn_remote_cmd(self.ssh, f'mkdir -p "$HOME"/{experiment_component}')
        self.dir = sn_remote_cmd(
            self.ssh, f'printf "%s\\n" "$HOME"/{experiment_component}'
        )
        self.sftp.put(
            os.path.join(os.path.dirname(__file__), 'sn_remote.py'),
            self.dir + '/sn_remote.py'
        )
        self.sftp.put(
            os.path.join(os.path.dirname(__file__), 'pyctr.c'),
            self.dir + '/pyctr.c'
        )
        sn_remote_cmd(
            self.ssh, 'rm -f ' + shlex.quote(self.dir + '/pyctr.so')
        )
        self.sftp.put(
            os.path.join(self.local_dir, ASSIGN_FILENAME),
            self.dir + '/' + ASSIGN_FILENAME
        )
        upload_folder(
            self.sftp,
            os.path.join(os.path.dirname(__file__), 'link_failure_grpc'),
            os.path.join(self.dir, 'link_failure_grpc')
        )
        controller_dir = os.path.join(self.dir,'controller')
        sn_remote_cmd(self.ssh, 'mkdir -p ' + shlex.quote(controller_dir))
        all_node_states_dir = os.path.join(self.dir,'all_node_states')
        sn_remote_cmd(self.ssh, 'mkdir -p ' + shlex.quote(all_node_states_dir))
        upload_folder(
            self.sftp,
            os.path.abspath(os.path.join(os.path.dirname(__file__), '..','geographic_srv6_anycast')),
            os.path.join(controller_dir, 'geographic_srv6_anycast')
        )

    def _python_command(self, script, *args):
        return ' '.join(
            shlex.quote(str(value))
            for value in (self.remote_python, script, *args)
        )

    def _resolve_remote_python_layout(self):
        marker = 'TINYLEO_PYTHON_LAYOUT='
        probe = (
            "import json,sys; print('" + marker + "' + json.dumps({"
            "'executable':sys.executable,'prefix':sys.prefix,"
            "'base_prefix':sys.base_prefix},sort_keys=True))"
        )
        output = sn_remote_wait_output(
            self.ssh, self._python_command('-c', probe)
        )
        matches = [
            json.loads(line[len(marker):])
            for line in output.splitlines()
            if line.startswith(marker)
        ]
        if len(matches) != 1 or not isinstance(matches[0], dict):
            raise RuntimeError(
                "configured remote Python returned no unique runtime layout"
            )
        layout = matches[0]
        executable = layout.get('executable')
        prefix = layout.get('prefix')
        base_prefix = layout.get('base_prefix')
        if not all(
            isinstance(value, str) and value
            for value in (executable, prefix, base_prefix)
        ) or not os.path.isabs(executable):
            raise RuntimeError("configured remote Python layout is invalid")
        self.remote_python_source = executable
        if prefix != base_prefix:
            prefix_with_separator = prefix.rstrip('/') + '/'
            if not os.path.isabs(prefix) or not executable.startswith(
                prefix_with_separator
            ):
                raise RuntimeError(
                    "configured venv executable is outside its runtime prefix"
                )
            relative_executable = executable[len(prefix_with_separator):]
            if not relative_executable or '..' in relative_executable.split('/'):
                raise RuntimeError("configured venv executable path is unsafe")
            self.venv_source = prefix
            self.container_python = '/resources/venv/' + relative_executable
        else:
            # Legacy system-Python configurations are safe only when the probe
            # resolves an absolute executable already present in lowerdir=/.
            self.venv_source = ''
            self.container_python = executable
        self.controller_source = os.path.join(self.dir, 'controller')

    
    def init_nodes(self):
        """
        Initializes nodes (e.g., satellites and ground stations) on the remote machine.
        """
        if not hasattr(self, 'container_python'):
            self._resolve_remote_python_layout()
        sn_remote_wait_output(
            self.ssh,
            self._python_command(
                f"{self.dir}/sn_remote.py", "nodes", self.id, self.dir,
                self.controller_source, self.venv_source,
            )
        )
        self.sftp.get(
            os.path.join(self.dir, PID_FILENAME),
            os.path.join(self.local_dir, PID_FILENAME)
        )
    
    def get_nodes(self):
        """
        Retrieves the list of nodes initialized on the remote machine.

        Returns:
            list: A list of node names.
        """
        lines = sn_remote_cmd(
            self.ssh,
            self._python_command(
                f"{self.dir}/sn_remote.py", "list", self.id, self.dir
            )
        ).splitlines()[1:]
        nodes = [
            line.split()[0] for line in lines
        ]
        return nodes
    
    def init_network(self, isl_bw, isl_loss, gsl_bw, gsl_loss):
        """
        Initializes the network configuration on the remote machine.

        Args:
            isl_bw (int): Bandwidth for inter-satellite links.
            isl_loss (float): Packet loss rate for inter-satellite links.
            gsl_bw (int): Bandwidth for ground station links.
            gsl_loss (float): Packet loss rate for ground station links.
        """
        for shell_name, sat_names in self.shell_lst:
            isl_dir = os.path.join(self.dir, shell_name,'isl')
            sn_remote_cmd(self.ssh, 'mkdir -p ' + shlex.quote(isl_dir))
            self.sftp.put(
                os.path.join(self.local_dir, shell_name, 'isl', 'init.txt'),
                os.path.join(isl_dir, 'init.txt')
            )
        if self.gs_dirname is not None:
            gsl_dir = os.path.join(self.dir, self.gs_dirname, 'gsl')
            sn_remote_cmd(self.ssh, 'mkdir -p ' + shlex.quote(gsl_dir))
        self.update_network(-1, isl_bw, isl_loss, gsl_bw, gsl_loss)

    def upload_failure_recovery_file(self, t):
        """
        Uploads failure recovery files to the remote machine.

        Args:
            t (int): The timestamp of the failure recovery files to be uploaded.

        Steps:
            1. Upload the JSON file containing the updated node states for the given timestamp
            from the local directory to the remote machine.
            2. For each shell in the simulation:
                - Upload the ISL (Inter-Satellite Link) configuration file for the given timestamp
                from the local directory to the corresponding directory on the remote machine.
        """
        self.sftp.put(
            os.path.join(self.local_dir, 'all_node_states', f'{t}.json'),
            os.path.join(self.dir, 'all_node_states', f'{t}.json')
        )
        for shell_name, sat_names in self.shell_lst:
            self.sftp.put(
                os.path.join(self.local_dir, shell_name, 'isl', f'{t}.txt'),
                os.path.join(self.dir, shell_name,'isl', f'{t}.txt')
            )

    def update_network(self, t, isl_bw, isl_loss, gsl_bw, gsl_loss):
        """
        Updates the network configuration on the remote machine for a specific timestamp.

        Args:
            t (int): Timestamp for the network update (-1 for initialization).
            isl_bw (int): Bandwidth for inter-satellite links.
            isl_loss (float): Packet loss rate for inter-satellite links.
            gsl_bw (int): Bandwidth for ground station links.
            gsl_loss (float): Packet loss rate for ground station links.
        """
        if t != -1:
            self.sftp.put(
                os.path.join(self.local_dir, 'all_node_states', f'{t}.json'),
                os.path.join(self.dir, 'all_node_states', f'{t}.json')
            )
            for shell_name, sat_names in self.shell_lst:
                self.sftp.put(
                    os.path.join(self.local_dir, shell_name, 'isl', f'{t}.txt'),
                    os.path.join(self.dir, shell_name,'isl', f'{t}.txt')
                )
            if self.gs_dirname is not None:
                self.sftp.put(
                    os.path.join(self.local_dir, self.gs_dirname, 'gsl', f'{t}.txt'),
                    os.path.join(self.dir, self.gs_dirname, 'gsl', f'{t}.txt')
                )
        sn_remote_wait_output(
            self.ssh,
            self._python_command(
                f"{self.dir}/sn_remote.py", "networks", self.id, self.dir,
                t, isl_bw, isl_loss, gsl_bw, gsl_loss,
            )
        )

    def fault_test(self, t, isl_bw, isl_loss, gsl_bw, gsl_loss, failed_link):
        """
        Simulates a fault test on the remote machine by introducing link failures.
        """
        output = sn_remote_wait_output(
            self.ssh,
            self._python_command(
                f"{self.dir}/sn_remote.py", "fault_test", self.id, self.dir,
                t, isl_bw, isl_loss, gsl_bw, gsl_loss, *failed_link,
                self.failure_controller_endpoint,
            )
        )
        marker = 'TINYLEO_FAILURE_ACK='
        acknowledgements = [
            json.loads(line[len(marker):])
            for line in output.splitlines()
            if line.startswith(marker)
        ]
        if len(acknowledgements) != 1:
            raise RuntimeError(
                "remote fault command returned no unique acknowledgement"
            )
        acknowledgement = acknowledgements[0]
        if acknowledgement.get('remote_id') != self.id:
            raise RuntimeError("remote fault acknowledged a different remote")
        return acknowledgement

    def deploy_tinyleo_srv6_agent(self):
        """
        Deploy the SRv6 agent on the remote machine for data plane operations.
        """
        if not hasattr(self, 'container_python'):
            self._resolve_remote_python_layout()
        agent_source = (
            f"{self.controller_source}/geographic_srv6_anycast/srv6_agent.py"
        )
        output = sn_remote_wait_output(
            self.ssh,
            self._python_command(
                f"{self.dir}/controller/geographic_srv6_anycast/deploy_srv6_agent.py",
                "--workdir", self.dir,
                "--python-executable", self.container_python,
                "--python-source", self.remote_python_source,
                "--agent-source", agent_source,
                "--agent-target",
                "/resources/controller/geographic_srv6_anycast/srv6_agent.py",
                "--remote-id", self.id,
            )
        )
        marker = 'TINYLEO_SRV6_DEPLOY_ACK='
        acknowledgements = [
            json.loads(line[len(marker):])
            for line in output.splitlines()
            if line.startswith(marker)
        ]
        if len(acknowledgements) != 1:
            raise RuntimeError(
                "SRv6 deploy command returned no unique acknowledgement"
            )
        acknowledgement = acknowledgements[0]
        if acknowledgement.get('remote_id') != self.id:
            raise RuntimeError("SRv6 deploy acknowledged a different remote")
        return acknowledgement

    def ping_async(self, res_path, src, dst):
        """
        Executes a ping test asynchronously between two nodes.

        Args:
            res_path (str): Path to save the ping results.
            src (str): Source node name.
            dst (str): Destination node name.

        Returns:
            threading.Thread: The thread executing the ping test.
        """
        def _ping_inner(ssh, dir, res_path, src, dst):
            output = sn_remote_cmd(
                ssh,
                self._python_command(
                    f"{dir}/sn_remote.py", "ping", self.id, dir, src, dst
                ) + " 2>&1"
            )
            with open(res_path, 'w') as f:
                f.write(output)
        return _start_result_thread(
            _ping_inner, self.ssh, self.dir, res_path, src, dst
        )
    
    def iperf_async(self, res_path, src, dst):
        """
        Executes an iperf test asynchronously between two nodes.

        Args:
            res_path (str): Path to save the iperf results.
            src (str): Source node name.
            dst (str): Destination node name.

        Returns:
            threading.Thread: The thread executing the iperf test.
        """
        def _iperf_inner(ssh, dir, res_path, src, dst):
            output = sn_remote_cmd(
                ssh,
                self._python_command(
                    f"{self.dir}/sn_remote.py", "iperf", self.id,
                    self.dir, src, dst,
                ) + " 2>&1"
            )
            with open(res_path, 'w') as f:
                f.write(output)

        return _start_result_thread(
            _iperf_inner, self.ssh, self.dir, res_path, src, dst
        )
    
    def traceroute_async(self, res_path, src, dst):
        """
        Executes a traceroute test asynchronously between two nodes.

        Args:
            res_path (str): Path to save the traceroute results.
            src (str): Source node name.
            dst (str): Destination node name.

        Returns:
            threading.Thread: The thread executing the traceroute test.
        """
        def _traceroute_async(ssh, dir, res_path, src, dst):
            output = sn_remote_cmd(
                ssh,
                self._python_command(
                    f"{self.dir}/sn_remote.py", "traceroute", self.id,
                    self.dir, src, dst,
                ) + " 2>&1"
            )
            with open(res_path, 'w') as f:
                f.write(output)

        return _start_result_thread(
            _traceroute_async, self.ssh, self.dir, res_path, src, dst
        )
    
    def check_utility(self, res_path):
        """
        Checks the system utility (e.g., CPU, memory usage) on the remote machine.

        Args:
            res_path (str): Path to save the utility check results.
        """
        output = sn_remote_cmd(self.ssh, "vmstat 2>&1")
        with open(res_path, 'w') as f:
            f.write(output)
        
    def clean(self):
        """
        Cleans up the remote machine by removing containers and resetting the environment.
        """
        sn_remote_cmd(
            self.ssh,
            self._python_command(
                f"{self.dir}/sn_remote.py", "clean", self.id, self.dir
            )
        )
