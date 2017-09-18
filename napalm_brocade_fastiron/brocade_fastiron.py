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

import re
import uuid
import tempfile


class BrocadeFastironDriver(NetworkDriver):
    """Napalm driver for Brocade Fastiron."""

    def __init__(self, hostname, username, password, timeout=60, optional_args=None):
        if optional_args is None:
            optional_args = {}
        self.device = None
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout
        self.os_version = None

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
        self._set_os_version()
        print type(self.device)

    def close(self):
        """Implementation of NAPALM method close."""

        self.device.disconnect()

    def _set_os_version(self):
        """
        Sets the local os_version variable since some commands and output
        differ between version 7 and 8
        """
        cmd = 'show version | include SW: Version'
        output = self._send_command(cmd)
        self.os_version = int(output.splitlines()[0].split()[2].split('.')[0])

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
        return output.strip()

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
        return config

    def load_merge_candidate(self, filename=None, config=None):
        pass

    def commit_config(self):
        pass

    def get_arp_table(self):

        arp_table = list()

        arp_cmd = 'show arp'
        output = self.device.send_command(arp_cmd)
        output = output.split('\n')
        output = output[3:]

        for line in output:
            fields = line.split()
            if len(fields) == 7:
                num, address, mac, typ, age, interface, status = fields
                try:
                    if age == 'None':
                        age = 0
                    age = float(age)
                except ValueError:
                    print(
                        "Unable to convert age value to float: {}".format(age)
                        )

                if "None" in mac:
                    mac = "00:00:00:00:00:00"
                else:
                    mac = napalm_base.helpers.mac(mac)

                if status == 'Valid':
                    entry = {
                        'interface': interface,
                        'mac': mac,
                        'ip': address,
                        'age': age
                    }
                    arp_table.append(entry)

        return arp_table
