# Copyright 2016 Dravetech AB. All rights reserved.
#
# The contents of this file are licensed under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with the
# License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

"""
Napalm driver for Brocade Fastiron.
"""

from netmiko import ConnectHandler
from netmiko import __version__ as netmiko_version
from napalm_base.base import NetworkDriver
import napalm_base.helpers
from napalm_base.exceptions import (
    ConnectionException,
    SessionLockedException,
    MergeConfigException,
    ReplaceConfigException,
    CommandErrorException,
    )
import napalm_base.helpers
from netaddr import IPNetwork
import re


class BrocadeFastironDriver(NetworkDriver):
    """Napalm driver for Brocade Fastiron."""

    def __init__(self, hostname, username, password, timeout=60,
                 optional_args=None):
        if optional_args is None:
            optional_args = {}
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout

        self.device = None
        self._os_version = None
        self._merge_cfg = None

        # Netmiko possible arguments
        netmiko_argument_map = {
            'port': None,
            'secret': '',
            'verbose': False,
            'global_delay_factor': 1,
            'use_keys': False,
            'key_file': None,
            'ssh_strict': False,
            'system_host_keys': False,
            'alt_host_keys': False,
            'alt_key_file': '',
            'ssh_config_file': None,
        }

        fields = netmiko_version.split('.')
        fields = [int(x) for x in fields]
        maj_ver, min_ver, bug_fix = fields
        if maj_ver >= 2:
            netmiko_argument_map['allow_agent'] = False
        elif maj_ver == 1 and min_ver >= 1:
            netmiko_argument_map['allow_agent'] = False

        # Build dict of any optional Netmiko args
        self.netmiko_optional_args = {}
        for k, v in netmiko_argument_map.items():
            try:
                self.netmiko_optional_args[k] = optional_args[k]
            except KeyError:
                pass
        self.global_delay_factor = optional_args.get('global_delay_factor', 1)
        self.port = optional_args.get('port', 22)


    def open(self):
        """Implementation of NAPALM method open."""
        self.device = ConnectHandler(device_type='brocade_fastiron',
                                     host=self.hostname,
                                     username=self.username,
                                     password=self.password,
                                     **self.netmiko_optional_args)
        self.device.enable()
        self._get_os_version()

    def close(self):
        """Implementation of NAPALM method close."""

        self.device.disconnect()

    def _get_os_version(self):
        """
        Sets the local os_version variable because some commands and output
        differ between version 7 and 8
        """
        cmd = 'show version | include SW: Version'
        output = self._send_command(cmd)
        self._os_version = int(output.splitlines()[0].split()[2].split('.')[0])

    def _send_command(self, command):
        """
        Wrapper for self.device.send.command().
        If command is a list will iterate through commands until valid command.
        """
        if isinstance(command, list):
            for cmd in command:
                output = self.device.send_command(cmd)
                if 'Invalid input' not in output:
                    break
        else:
            output = self.device.send_command(command)
        return output

    def _write_memory(self):
        pass

    def is_alive(self):
        """Returns a flag with the state of the SSH connection."""
        return {
            'is_alive': self.device.remote_conn.transport.is_active()
        }

    def cli(self, commands):
        cli_output = dict()
        if type(commands) is not list:
            raise TypeError('Please enter a valid list of commands!')

        for command in commands:
            output = self._send_command(command)
            if 'Invalid input' in output:
                raise ValueError(
                    'Unable to execute command "{}"'.format(command))
            cli_output.setdefault(command, {})
            cli_output[command] = output

        return cli_output

    def get_config(self, retrieve='all'):
        """Implementation of get_config for Brocade Fastiron"""

        configs = {
            'startup': '',
            'running': '',
            'candidate': '',
        }

        if retrieve.lower() in ('running', 'all'):
            command = 'show running-config'
            configs['running'] = self._send_command(command)
        if retrieve.lower() in ('startup', 'all'):
            command = 'show configuration'
            configs['startup'] = self._send_command(command)
        return configs

    def load_merge_candidate(self, filename=None, config=None):
        if filename and config:
            raise ValueError("Cannot simultaneously set filename and config")

        if filename:
            with open(filename, 'r') as fobj:
                self._merge_cfg = filter(None, (l.strip() for l in fobj))

        if config:
            if isinstance(config, list):
                self._merge_cfg = filter(None, (l.strip() for l in config))
            else:
                self._merge_cfg = filter(None,
                                       (l.strip() for l in config.splitlines()))

    def commit_config(self):
        output = self.device.send_config_set(self._merge_cfg)
        self._send_command('write memory')
        return output

    def get_arp_table(self):
        """Get arp table information."""
        arp_table = list()
        cmd = 'show arp'
        output = self._send_command(cmd).splitlines()

        # Skip over the heacder
        if self._os_version == 7:
            output = output[2:]
        if self._os_version == 8:
            output = output[3:]

        for line in output:
            fields = line.split()
            if len(fields) == 7:
                num, address, mac, typ, age, interface, state = fields

                try:
                    age = float(age)
                except ValueError:
                    raise ValueError("Unable to convert age value to float: {}".format(age))

                if 'None' in mac:
                    mac = napalm_base.helpers.mac("00:00:00:00:00:00")
                else:
                    mac = napalm_base.helpers.mac(mac)

                entry = {
                    'interface': interface,
                    'mac': mac,
                    'ip': address,
                    'age': age
                }

                arp_table.append(entry)

        return arp_table

    def _parse_port_change(self, string):
        # 632 days 18 hours 20 minutes 40 seconds
        # 3 days 36 minutes 18 seconds
        # 1 seconds
        days, hours, mins, secs = [0,0,0,0]
        re_d = re.search('(\d+) days', string)
        re_h = re.search('(\d+) hours', string)
        re_m = re.search('(\d+) minutes', string)
        re_s = re.search('(\d+) seconds', string)

        if re_d:
            days = int(re_d.group(1))
        if re_h:
            hours = int(re_h.group(1))
        if re_m:
            mins = int(re_m.group(1))
        if re_s:
            secs = int(re_s.group(1))

        t = secs + (mins*60) + (hours*60*60) + (days*24*60*60)
        if t == 0:
            return -1
        return t

    def _calc_speed(self, speed):
        unit = speed[-4]
        if unit == 'M':
            s = int(speed[:-4])
        else:
            s = int(speed[:-4]) * 1000
        return s

    def _get_interface_details(self, port):
        re_mgmt = re.match('mgmt(\d+)', port)
        if re_mgmt:
            cmd = 'show interface management {}'.format(re_mgmt.group(1))
        else:
            cmd = 'show interface ethernet {}'.format(port)
        output = self._send_command(cmd)

        last_flap = -1
        description = ''
        speed = 1000

        if self._os_version == 8:
            last_flap = re.search(r'Port \S+ for (\d.*seconds)', output).group(1)
            last_flap = self._parse_port_change(last_flap)

        re_desc = re.search(r'\sPort name is (.*)', output, re.MULTILINE)
        if re_desc:
            description = re_desc.group(1)

        re_speed = re.search('\sConfigured speed (\S+), actual (\S+),', output)
        if 'unknown' not in re_speed.group(2):
            speed = self._calc_speed(re_speed.group(2))
        elif 'auto' not in re_speed.group(1):
            speed = self._calc_speed(re_speed.group(1))

        return [last_flap, description, speed]

    def _get_logical_interface_detail(self, port):
        port = port.replace('lb', 'loopback')
        cmd = 'show interface {}'.format(port)
        output = self._send_command(cmd)

        speed = -1
        last_flap = -1
        description = ''

        re_desc = re.search(r'\sPort name is (.*)', output, re.MULTILINE)
        if re_desc:
            description = re_desc.group(1)

        return [last_flap, description, speed]

    def get_interfaces(self):
        """Get interface details."""
        interface_list = dict()

        cmd = 'sh interfaces brief'
        output = self._send_command(cmd).splitlines()

        for line in output:
            fields = line.split()

            if len(fields) == 0:
                continue
            if fields[0] == 'Port':
                continue

            port, link, state = fields[:3]
            speed = fields[4]
            mac = fields[9]

            if 'N/A' not in mac:
                mac = napalm_base.helpers.mac(mac)

            if re.match('(\d+/\d+)', port):
                is_up = bool('forward' in state.lower())
                is_enabled = not bool('disable' in link.lower())
                port_details = self._get_interface_details(port)
            elif re.match('(ve|lb|mgmt)\d+', port):
                is_enabled = not bool('down' in link.lower())
                is_up = is_enabled
                if 'mgmt' in port:
                    port_details = self._get_interface_details(port)
                else:
                    port_details = self._get_logical_interface_detail(port)
            else:
                continue

            interface_list[port] = {
                'is_up': is_up,
                'is_enabled': is_enabled,
                'description': unicode(port_details[1]),
                'last_flapped': float(port_details[0]),
                'speed': port_details[2],
                'mac_address': mac
            }

        return interface_list

    def _get_detailed_counters(self, port):
        counters = dict()
        re_mgmt = re.match('mgmt(\d+)', port)
        if re_mgmt:
            cmd = 'show statistics management {}'.format(re_mgmt.group(1))
        else:
            cmd = 'show statistics ethernet {}'.format(port)

        output = self._send_command(cmd)

        octets = re.search(r'InOctets\s+(\d+)\s+OutOctets\s+(\d+)', output)
        if octets:
            counters['rx_octets'] = octets.group(1)
            counters['tx_octets'] = octets.group(2)

        packets = re.search(r'InUnicastPkts\s+(\d+)\s+OutUnicastPkts\s+(\d+)',
                            output)
        if packets:
            counters['rx_unicast_packets'] = packets.group(1)
            counters['rx_unicast_packets'] = packets.group(2)

        multicast = re.search(r'InMulticastPkts\s+(\d+)\s+OutMulticastPkts\s+(\d+)',
                              output)
        if multicast:
            counters['rx_multicast_packets'] = multicast.group(1)
            counters['tx_multicast_packets'] = multicast.group(2)

        broadcast = re.search(r'InBroadcastPkts\s+(\d+)\s+OutBroadcastPkts\s+(\d+)',
                              output)
        if broadcast:
            counters['rx_broadcast_packets'] = broadcast.group(1)
            counters['tx_broadcast_packets'] = broadcast.group(2)

        discards = re.search(r'InDiscards\s+(\d+)', output)
        if discards:
            counters['rx_discards'] = discards.group(1)

        out_errors = re.search(r'OutErrors\s+(\d+)', output)
        if out_errors:
            counters['tx_errors'] = out_errors.group(1)

        in_errors = re.search(r'InErrors\s+(\d+)', output)
        if in_errors:
            counters['rx_errors'] = in_errors.group(1)

        return counters

    def get_interfaces_counters(self):
        counters = dict()
        cmd = 'show statistics'
        output = self._send_command(cmd).splitlines()
        output = output[2:-1]

        ports = list()
        for line in output:
            fields = line.split()
            ports.append(fields[0])

        for port in ports:
            counters[port] = self._get_detailed_counters(port)

        return counters

    def get_mac_address_table(self):
        mac_address_table = list()
        cmd = 'show mac-address'
        output = self._send_command(cmd).splitlines()
        output = output[2:]

        for line in output:
            fields = line.split()
            if len(fields) == 5 and 'MAC-Address' not in fields[0]:
                mac, port, mtype, index, vlan = fields
                is_static = not bool('Dynamic' in mtype)
                mac = napalm_base.helpers.mac(mac)

                entry = {
                    'mac': mac,
                    'interface': unicode(port),
                    'vlan': int(vlan),
                    'active': True,
                    'static': is_static,
                    'moves': -1,
                    'last_move': float(-1)
                }

                mac_address_table.append(entry)

        return mac_address_table

    def get_interfaces_ip(self):
        interfaces = dict()
        config = self.get_config(retrieve='running')['running'].splitlines()

        for line in config:
            re_int = re.match('interface\s(\S+)\s(\S+)', line)
            if re_int:
                if_block = True
                port = "{}{}".format(re_int.group(1),re_int.group(2))
                port = port.replace('ethernet', '')
                port = port.replace('loopback', 'lb')
                port = port.replace('management', 'mgmt')
                port = port.replace('ve', 'v')
                continue

            re_ip = re.search('^\s(ip|ipv6) address (.*)', line)
            if re_ip:
                ip = re_ip.group(2)
                ip = ip.replace(' dynamic', '')
                ip = ip.replace(' ', '/')
                ip = IPNetwork(ip)
                ver = "ipv{}".format(ip.version)

                if port not in interfaces:
                    interfaces[port] = dict()
                if ver not in interfaces[port]:
                    interfaces[port][ver] = dict()

                interfaces[port][ver][str(ip.ip)] = {'prefix_length': ip.prefixlen}

        return interfaces

    def get_lldp_neighbors(self):
        pass

    def get_lldp_neighbors_detail(self, interface=''):
        pass

    def get_environment(self):
        pass

    def get_ntp_servers(self):
        pass

    def get_ntp_stats(self):
        pass

    def get_route_to(self, destination='', protocol=''):
        pass

    def get_mac_address_table(self):

        cmd = "show mac-address"
        lines = self.device.send_command(cmd)
        lines = lines.split('\n')

        mac_address_table = []
        lines = lines[2:]

        for line in lines:
            fields = line.split()

            if len(fields) == 4:
                mac_address, port, typ, vlan = fields
            
                is_static = not bool('Dynamic' in typ)
                mac_address = napalm_base.helpers.mac(mac_address)

                entry = {
                   'mac': mac_address,
                   'interface': unicode(port),
                   'vlan': int(vlan),
                   'active': bool(1),
                   'static': is_static,
                   'moves': -1,
                   'last_move': float(-1)
                }
                mac_address_table.append(entry)
            
        return mac_address_table
