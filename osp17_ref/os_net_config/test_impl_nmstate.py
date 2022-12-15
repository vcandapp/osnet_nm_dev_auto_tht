# -*- coding: utf-8 -*-

# Copyright 2014 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os.path
import tempfile
import yaml

from libnmstate import netapplier

import os_net_config
from os_net_config import impl_nmstate
from os_net_config import objects
from os_net_config.tests import base
from os_net_config import utils

_BASE_NMCFG = """- name: em1
  type: ethernet
  state: up
"""

_NO_IP = _BASE_NMCFG + """  ipv4:
    enabled: false
  ipv6:
    enabled: false
"""

_V4_NMCFG = _BASE_NMCFG + """  ipv6:
    enabled: False
  ipv4:
    enabled: True
    address:
    - ip: 192.168.1.2
      prefix-length: 24
"""

_V4_NMCFG_MULTIPLE = _V4_NMCFG + """    - ip: 192.168.2.2
      prefix-length: 32
    - ip: 10.0.0.2
      prefix-length: 8
"""

_V4_NMCFG_MAPPED = _V4_NMCFG + """
  802-3-Ethernet.cloned-mac-address: a1:b2:c3:d4:e5
"""

_V4_V6_NMCFG = _BASE_NMCFG + """  ipv6:
    enabled: True
    autoconf: False
    address:
    - ip: 2001:abc:a::2
      prefix-length: 64
  ipv4:
    enabled: True
    address:
    - ip: 192.168.1.2
      prefix-length: 24
"""

_NMCFG_VLAN = """- name: em1.120
  type: vlan
  vlan:
    id: 120
    base-iface: em1
  state: up
  ipv4:
    enabled: false
  ipv6:
    enabled: false
"""

_NMCFG_STATE = [{'name': 'em4', 'state': 'down', 'mtu': 1500,
                 'type': 'ethernet',
                 'ipv6': {'autoconf': True, 'auto-gateway': True,
                          'enabled': True, 'auto-routes': True,
                          'address': [], 'dhcp': True, 'auto-dns': True},
                 'ipv4': {'auto-gateway': True, 'enabled': True,
                          'auto-routes': True, 'address': [], 'dhcp': True,
                          'auto-dns': True}},
                {'name': 'em1', 'state': 'up', 'mtu': 1500, 'type': 'ethernet',
                 'ethernet': {'duplex': 'full', 'speed': 1000,
                              'auto-negotiation': True},
                 'ipv6': {'autoconf': True, 'auto-gateway': True,
                          'enabled': True, 'auto-routes': True,
                          'address': [{'ip': 'fd00:dada:1337:2::1bb8:af8c',
                                       'prefix-length': 64},
                                      {'ip': 'fd00:dada:1337:2::5d9',
                                       'prefix-length': 128}],
                          'dhcp': True, 'auto-dns': True},
                 'ipv4': {'auto-gateway': True, 'enabled': True,
                          'auto-routes': True,
                          'address': [{'ip': '192.168.1.234',
                                       'prefix-length': 24}],
                          'dhcp': True, 'auto-dns': True}},
                {'state': 'down', 'name': 'em2', 'ipv6': {'enabled': False},
                 'mtu': 1500, 'type': 'ethernet', 'ipv4': {'enabled': False}},
                {'state': 'down', 'name': 'em3', 'ipv6': {'enabled': False},
                 'mtu': 1500, 'type': 'ethernet', 'ipv4': {'enabled': False}},
                {'state': 'down', 'name': 'lo', 'ipv6': {'enabled': False},
                 'mtu': 65536, 'type': 'unknown', 'ipv4': {'enabled': False}},
                ]

_IFCFG_ROUTES1 = """default via 192.0.2.1 dev eth0
192.0.2.1/24 via 192.0.2.1 dev eth0
"""

_IFCFG_ROUTES2 = """default via 192.0.1.1 dev eth0
192.0.1.1/24 via 192.0.3.1 dev eth1
"""

_V6_NMCFG = _BASE_NMCFG + """  ipv4:
    enabled: False
  ipv6:
    enabled: True
    autoconf: False
    address:
    - ip: "2001:abc:a::"
      prefix-length: 64
"""

_V6_NMCFG_MULTIPLE = _V6_NMCFG + """    - ip: 2001:abc:b::1
      prefix-length: 64
    - ip: 2001:abc:c::2
      prefix-length: 96
"""

_ROUTES = """default via 192.168.1.1 dev em1 metric 10
172.19.0.0/24 via 192.168.1.1 dev em1
172.20.0.0/24 via 192.168.1.5 dev em1 metric 100
"""

_ROUTES_V6 = """default via 2001:db8::1 dev em1
2001:db8:dead:beef:cafe::/56 via fd00:fd00:2000::1 dev em1
2001:db8:dead:beff::/64 via fd00:fd00:2000::1 dev em1 metric 100
"""

_OVS_INTERFACE = _NO_IP + """
- name: ovs-br-simple
  type: ovs-bridge
  state: up
  bridge:
    port:
    - name: em1
"""

_OVS_BRIDGE_DHCP = _NO_IP + """
- name: br-ctlplane
  type: ovs-bridge
  state: up
  bridge:
    port:
    - name: em1
    options:
      fail-mode: standalone
      mcast-snooping-enable: False
      rstp: False
      stp: False
  ipv4:
    dhcp: True
    enabled: True
  ipv6:
    enabled: False
"""

_OVS_BRIDGE_DHCP_STANDALONE = """
- name: br-ctlplane
  type: ovs-bridge
  state: up
  bridge:
    port:
    - name: em1
    options:
      fail-mode: 'standalone'
      mcast-snooping-enable: False
      rstp: False
      stp: False
  ipv4:
    dhcp: True
    enabled: True
  ipv6:
    enabled: False
"""

_OVS_BRIDGE_DHCP_SECURE = """
- name: br-ctlplane
  type: ovs-bridge
  state: up
  bridge:
    port:
    - name: em1
    options:
      fail-mode: 'secure'
      mcast-snooping-enable: False
      rstp: False
      stp: False
  ipv4:
    enabled: True
    dhcp: True
  ipv6:
    enabled: False
"""


_OVS_BRIDGE_STATIC = """
- name: br-ctlplane
  type: ovs-bridge
  state: up
  bridge:
    options:
      fail-mode: standalone
      mcast-snooping-enable: False
      rstp: False
      stp: False
    port:
    - name: em1
  ipv4:
    enabled: True
    address:
    - ip: 192.168.1.2
      prefix-length: 24
  ipv6:
    enabled: False
"""

_OVS_BRIDGE_DHCP_MAC = _OVS_BRIDGE_DHCP + """
  mac-address: a1:b2:c3:d4:e5
"""

_BASE_VLAN = """- name: vlan5
  type: vlan
  vlan:
    id: 5
    base-iface: em1
  state: up
"""

_VLAN_NO_IP = _BASE_VLAN + """  ipv4:
    enabled: false
  ipv6:
    enabled: false
"""

_LINUX_BOND_DHCP = """- name: bond0
  type: bond
  state: up
  ipv4:
    enabled: True
    dhcp: True
  ipv6:
    enabled: False
  link-aggregation:
    mode: active-backup
    port:
      - em1
      - em2
    options: {}
"""

_LINUX_BOND_INTERFACE = _NO_IP + """
- name: em2
  type: ethernet
  state: up
  ipv4:
    enabled: False
  ipv6:
    enabled: False
- name: bond0
  type: bond
  state: up
  ipv4:
    enabled: False
  ipv6:
    enabled: False
"""


class TestNmstateNetConfig(base.TestCase):
    def setUp(self):
        super(TestNmstateNetConfig, self).setUp()

        self.provider = impl_nmstate.NmstateNetConfig()

        def stub_is_ovs_installed():
            return True
        self.stub_out('os_net_config.utils.is_ovs_installed',
                      stub_is_ovs_installed)

    def get_interface_config(self, name='em1'):
        return self.provider.interface_data[name]

    def get_bridge_config(self, name='br-ctlplane'):
        return self.provider.bridge_data[name]

    def get_vlan_config(self, name='vlan1'):
        return self.provider.vlan_data[name]

    def get_linux_bond_config(self, name='bond0'):
        return self.provider.linuxbond_data[name]

    def get_route_config(self, name='em1'):
        return self.provider.route_data.get(name, '')

    def get_route6_config(self, name='em1'):
        return self.provider.route6_data.get(name, '')

    def test_add_base_interface(self):
        interface = objects.Interface('em1')
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_NO_IP)[0],
                         self.get_interface_config())

    def test_add_base_interface_vlan(self):
        interface = objects.Interface('em1.120')
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_NMCFG_VLAN)[0],
                         self.get_interface_config('em1.120'))

    # TODO(dsneddon): Add test when nmstate supports OVS tunnel ports
    # def test_add_ovs_tunnel(self):
    #     interface = objects.OvsTunnel('tun0')
    #     interface.type = 'ovs_tunnel'
    #     interface.tunnel_type = 'gre'
    #     interface.ovs_options = ['options:remote_ip=192.168.1.1']
    #     interface.bridge_name = 'br-ctlplane'
    #     self.provider.add_interface(interface)
    #     self.assertEqual(_OVS_IFCFG_TUNNEL,
    #                      self.get_interface_config('tun0'))

    # TODO(dsneddon): Add test when nmstate support OVS patch ports
    # def test_add_ovs_patch_port(self):
    #     patch_port = objects.OvsPatchPort("br-pub-patch")
    #     patch_port.type = 'ovs_patch_port'
    #     patch_port.bridge_name = 'br-ex'
    #     patch_port.peer = 'br-ex-patch'
    #     self.provider.add_interface(patch_port)
    #     self.assertEqual(_OVS_IFCFG_PATCH_PORT,
    #                      self.get_interface_config('br-pub-patch'))

    def test_add_interface_with_v4(self):
        v4_addr = objects.Address('192.168.1.2/24')
        interface = objects.Interface('em1', addresses=[v4_addr])
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_V4_NMCFG)[0],
                         self.get_interface_config())
        self.assertEqual('', self.get_route_config())

    def test_add_interface_with_v4_multiple(self):
        addresses = [objects.Address('192.168.1.2/24'),
                     objects.Address('192.168.2.2/32'),
                     objects.Address('10.0.0.2/8')]
        interface = objects.Interface('em1', addresses=addresses)
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_V4_NMCFG_MULTIPLE)[0],
                         self.get_interface_config())
        self.assertEqual('', self.get_route_config())

    def test_add_interface_with_v6(self):
        v6_addr = objects.Address('2001:abc:a::/64')
        interface = objects.Interface('em1', addresses=[v6_addr])
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_V6_NMCFG)[0],
                         self.get_interface_config())

    def test_add_interface_with_v6_multiple(self):
        addresses = [objects.Address('2001:abc:a::/64'),
                     objects.Address('2001:abc:b::1/64'),
                     objects.Address('2001:abc:c::2/96')]
        interface = objects.Interface('em1', addresses=addresses)
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_V6_NMCFG_MULTIPLE)[0],
                         self.get_interface_config())

    def test_network_with_routes(self):
        route1 = objects.Route('192.168.1.1', default=True,
                               route_options="metric 10")
        route2 = objects.Route('192.168.1.1', '172.19.0.0/24')
        route3 = objects.Route('192.168.1.5', '172.20.0.0/24',
                               route_options="metric 100")
        v4_addr = objects.Address('192.168.1.2/24')
        interface = objects.Interface('em1', addresses=[v4_addr],
                                      routes=[route1, route2, route3])
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_V4_NMCFG)[0],
                         self.get_interface_config())
        self.assertEqual(_ROUTES, self.get_route_config())

    def test_network_with_ipv6_routes(self):
        route1 = objects.Route('192.168.1.1', default=True,
                               route_options="metric 10")
        route2 = objects.Route('192.168.1.1', '172.19.0.0/24')
        route3 = objects.Route('192.168.1.5', '172.20.0.0/24',
                               route_options="metric 100")
        route4 = objects.Route('2001:db8::1', default=True)
        route5 = objects.Route('fd00:fd00:2000::1',
                               '2001:db8:dead:beef:cafe::/56')
        route6 = objects.Route('fd00:fd00:2000::1',
                               '2001:db8:dead:beff::/64',
                               route_options="metric 100")
        v4_addr = objects.Address('192.168.1.2/24')
        v6_addr = objects.Address('2001:abc:a::2/64')
        interface = objects.Interface('em1', addresses=[v4_addr, v6_addr],
                                      routes=[route1, route2, route3,
                                              route4, route5, route6])
        self.provider.add_interface(interface)
        self.assertEqual(yaml.safe_load(_V4_V6_NMCFG)[0],
                         self.get_interface_config())
        self.assertEqual(_ROUTES_V6, self.get_route6_config())

    def test_network_ovs_bridge(self):
        interface = objects.Interface('em1')
        bridge = objects.OvsBridge('br-ctlplane', use_dhcp=True,
                                   members=[interface])
        self.provider.add_interface(interface)
        self.provider.add_bridge(bridge)
        self.assertEqual(yaml.safe_load(_NO_IP)[0],
                         self.get_interface_config())
        self.assertEqual(yaml.safe_load(_OVS_BRIDGE_DHCP)[1],
                         self.provider.bridge_data['br-ctlplane'])

    def test_network_ovs_bridge_with_standalone_fail_mode(self):
        interface = objects.Interface('em1')
        bridge = objects.OvsBridge('br-ctlplane', use_dhcp=True,
                                   members=[interface],
                                   fail_mode='standalone')
        self.provider.add_interface(interface)
        self.provider.add_bridge(bridge)
        self.assertEqual(yaml.safe_load(_NO_IP)[0],
                         self.get_interface_config())
        self.assertEqual(yaml.safe_load(_OVS_BRIDGE_DHCP_STANDALONE)[0],
                         self.provider.bridge_data['br-ctlplane'])

    def test_network_ovs_bridge_with_secure_fail_mode(self):
        interface = objects.Interface('em1')
        bridge = objects.OvsBridge('br-ctlplane', use_dhcp=True,
                                   members=[interface],
                                   fail_mode='secure')
        self.provider.add_interface(interface)
        self.provider.add_bridge(bridge)
        self.assertEqual(yaml.safe_load(_NO_IP)[0],
                         self.get_interface_config())
        self.assertEqual(yaml.safe_load(_OVS_BRIDGE_DHCP_SECURE)[0],
                         self.get_bridge_config('br-ctlplane'))

    def test_network_ovs_bridge_static(self):
        v4_addr = objects.Address('192.168.1.2/24')
        interface = objects.Interface('em1')
        bridge = objects.OvsBridge('br-ctlplane', members=[interface],
                                   addresses=[v4_addr])
        self.provider.add_interface(interface)
        self.provider.add_bridge(bridge)
        self.assertEqual(yaml.safe_load(_NO_IP)[0],
                         self.get_interface_config())
        self.assertEqual(yaml.safe_load(_OVS_BRIDGE_STATIC)[0],
                         self.provider.bridge_data['br-ctlplane'])

    def test_network_ovs_bridge_with_dhcp_primary_interface(self):
        def test_interface_mac(name):
            return "a1:b2:c3:d4:e5"
        self.stub_out('os_net_config.utils.interface_mac', test_interface_mac)

        interface = objects.Interface('em1', primary=True)
        ovs_extra = "br-set-external-id {name} bridge-id {name}"
        bridge = objects.OvsBridge('br-ctlplane', use_dhcp=True,
                                   members=[interface])
        self.provider.add_interface(interface)
        self.provider.add_bridge(bridge)
        self.assertEqual(yaml.safe_load(_NO_IP)[0],
                         self.get_interface_config('em1'))
        self.assertEqual(yaml.safe_load(_OVS_BRIDGE_DHCP_MAC)[1],
                         self.get_bridge_config('br-ctlplane'))

    def test_add_vlan(self):
        vlan = objects.Vlan('em1', 5)
        self.provider.add_vlan(vlan)
        self.assertEqual(yaml.safe_load(_VLAN_NO_IP)[0],
                         self.get_vlan_config('vlan5'))

    # TODO(dsneddon): Need nmstate to support OVS internal ports
    # def test_add_vlan_ovs(self):
    #     vlan = objects.Vlan('em1', 5)
    #     vlan.ovs_port = True
    #     self.provider.add_vlan(vlan)
    #     self.assertEqual(_VLAN_OVS, self.get_vlan_config('vlan5'))

    def test_add_vlan_mtu_1500(self):
        vlan = objects.Vlan('em1', 5, mtu=1500)
        self.provider.add_vlan(vlan)
        expected = _VLAN_NO_IP + '  mtu: 1500\n'
        self.assertEqual(yaml.safe_load(expected)[0],
                         self.get_vlan_config('vlan5'))

    # TODO(dsneddon): Need nmstate to support OVS internal ports
    # def test_add_ovs_bridge_with_vlan(self):
    #     vlan = objects.Vlan('em1', 5)
    #     bridge = objects.OvsBridge('br-ctlplane', use_dhcp=True,
    #                                members=[vlan])
    #     self.provider.add_vlan(vlan)
    #     self.provider.add_bridge(bridge)
    #     self.assertEqual(_VLAN_OVS_BRIDGE, self.get_vlan_config('vlan5'))

    def test_ovs_bond(self):
        interface1 = objects.Interface('em1')
        interface2 = objects.Interface('em2')
        bond = objects.OvsBond('bond0', use_dhcp=True,
                               members=[interface1, interface2])
        self.provider.add_interface(interface1)
        self.provider.add_interface(interface2)
        self.provider.add_bond(bond)
        self.assertEqual(yaml.safe_load(_NO_IP)[0],
                         self.get_interface_config('em1'))

        em2_config = """- name: em2
  type: ethernet
  state: up
  ipv4:
    enabled: False
  ipv6:
    enabled: False
"""
        self.assertEqual(yaml.safe_load(em2_config)[0],
                         self.get_interface_config('em2'))
        # TODO(dsneddon): Complete when nmstate supports OVS bonds
        # self.assertEqual(yaml.safe_load(_OVS_BOND_DHCP)[0],
        #                  self.get_interface_config('bond0'))

    def test_linux_bond(self):
        interface1 = objects.Interface('em1')
        interface2 = objects.Interface('em2')
        bond = objects.LinuxBond('bond0', use_dhcp=True,
                                 members=[interface1, interface2])
        self.provider.add_linux_bond(bond)
        self.provider.add_interface(interface1)
        self.provider.add_interface(interface2)
        self.assertEqual(yaml.safe_load(_LINUX_BOND_DHCP)[0],
                         self.get_linux_bond_config('bond0'))
        self.assertEqual(yaml.safe_load(_LINUX_BOND_INTERFACE)[0],
                         self.get_interface_config('em1'))
        self.assertEqual(yaml.safe_load(_LINUX_BOND_INTERFACE)[1],
                         self.get_interface_config('em2'))

    # TODO(dsneddon): Complete when team support is finalized for nmstate
    # def test_linux_team(self):
    #     interface1 = objects.Interface('em1')
    #     interface2 = objects.Interface('em2')
    #     team = objects.LinuxTeam('team0', use_dhcp=True,
    #                              members=[interface1, interface2])
    #     self.provider.add_linux_team(team)
    #     self.provider.add_interface(interface1)
    #     self.provider.add_interface(interface2)
    #     self.assertEqual(yaml.safe_load(_LINUX_TEAM_DHCP)[0],
    #                      self.get_linux_team_config('team0'))
    #     self.assertEqual(yaml.safe_load(_LINUX_TEAM_INTERFACE)[0],
    #                      self.get_interface_config('em1'))

    def test_interface_defroute(self):
        interface1 = objects.Interface('em1')
        interface2 = objects.Interface('em2', defroute=False)
        self.provider.add_interface(interface1)
        self.provider.add_interface(interface2)
        em1_config = """- name: em1
  type: ethernet
  state: up
  ipv4:
    enabled: False
  ipv6:
    enabled: False
"""
        em2_config = """- name: em2
  type: ethernet
  state: up
  ipv4:
    enabled: False
    auto-gateway: False
  ipv6:
    enabled: False
"""
        self.assertEqual(yaml.safe_load(em1_config)[0],
                         self.get_interface_config('em1'))
        self.assertEqual(yaml.safe_load(em2_config)[0],
                         self.get_interface_config('em2'))

    def test_interface_single_dns_server(self):
        interface1 = objects.Interface('em1', dns_servers=['1.2.3.4'])
        self.provider.add_interface(interface1)
        em1_config = """- name: em1
  type: ethernet
  state: up
  ipv4:
    auto-dns: False
    enabled: False
  ipv6:
    enabled: False
"""
        self.assertEqual(yaml.safe_load(em1_config)[0],
                         self.get_interface_config('em1'))

    def test_interface_dns_servers(self):
        # TODO(dsneddon): Write test when DNS servers are supported
        pass

    def test_interface_more_dns_servers(self):
        # TODO(dsneddon): Write test when DNS servers are supported
        pass


class TestNmstateNetConfigApply(base.TestCase):

    def setUp(self):
        super(TestNmstateNetConfigApply, self).setUp()
        self.temp_ifcfg_file = tempfile.NamedTemporaryFile()
        self.temp_bond_file = tempfile.NamedTemporaryFile()
        self.temp_route_file = tempfile.NamedTemporaryFile()
        self.temp_route6_file = tempfile.NamedTemporaryFile()
        self.temp_bridge_file = tempfile.NamedTemporaryFile()
        self.temp_cleanup_file = tempfile.NamedTemporaryFile(delete=False)
        self.ifup_interface_names = []
        self.ovs_appctl_cmds = []
        self.stop_dhclient_interfaces = []
        self.ip_reconfigure_commands = []

        def test_ifcfg_path(name):
            return self.temp_ifcfg_file.name
        self.stub_out(
            'os_net_config.impl_nmstate.ifcfg_config_path', test_ifcfg_path)

        def test_remove_ifcfg_config(name):
            ifcfg_file = self.temp_ifcfg_file.name
            if os.path.exists(ifcfg_file):
                os.remove(ifcfg_file)
        self.stub_out('os_net_config.impl_nmstate.remove_ifcfg_config',
                      test_remove_ifcfg_config)

        def test_routes_path(name):
            return self.temp_route_file.name
        self.stub_out(
            'os_net_config.impl_nmstate.route_config_path', test_routes_path)

        def test_routes6_path(name):
            return self.temp_route6_file.name
        self.stub_out(
            'os_net_config.impl_nmstate.route6_config_path', test_routes6_path)

        def test_bridge_path(name):
            return self.temp_bridge_file.name
        self.stub_out(
            'os_net_config.impl_nmstate.bridge_config_path', test_bridge_path)

        def test_cleanup_pattern():
            return self.temp_cleanup_file.name
        self.stub_out('os_net_config.impl_nmstate.cleanup_pattern',
                      test_cleanup_pattern)

        def test_stop_dhclient_process(interface):
            self.stop_dhclient_interfaces.append(interface)
        self.stub_out('os_net_config.impl_nmstate.stop_dhclient_process',
                      test_stop_dhclient_process)

        def test_execute(*args, **kwargs):
            if args[0] == '/sbin/ifup':
                self.ifup_interface_names.append(args[1])
            elif args[0] == '/bin/ovs-appctl':
                self.ovs_appctl_cmds.append(' '.join(args))
            elif args[0] == '/sbin/ip' or args[0] == '/usr/sbin/ip':
                self.ip_reconfigure_commands.append(' '.join(args[1:]))
            pass
        self.stub_out('oslo_concurrency.processutils.execute', test_execute)

        def stub_is_ovs_installed():
            return True
        self.stub_out('os_net_config.utils.is_ovs_installed',
                      stub_is_ovs_installed)

        def test_get_ifaces():
            return _NMCFG_STATE
        self.stub_out('libnmstate.netinfo.interfaces', test_get_ifaces)

        def test_iface_state(iface_data='', verify_change=True):
            # This function returns None
            return None
        self.stub_out(
            'libnmstate.netapplier.apply', test_iface_state)

        self.provider = impl_nmstate.NmstateNetConfig()

    def tearDown(self):
        self.temp_ifcfg_file.close()
        self.temp_route_file.close()
        self.temp_route6_file.close()
        self.temp_bridge_file.close()
        if os.path.exists(self.temp_cleanup_file.name):
            self.temp_cleanup_file.close()
        super(TestNmstateNetConfigApply, self).tearDown()

    def test_network_apply_routes(self):
        route1 = objects.Route('192.168.1.1', default=True,
                               route_options="metric 10")
        route2 = objects.Route('192.168.1.1', '172.19.0.0/24')
        route3 = objects.Route('192.168.1.5', '172.20.0.0/24',
                               route_options="metric 100")
        v4_addr = objects.Address('192.168.1.2/24')
        interface = objects.Interface('em1', addresses=[v4_addr],
                                      routes=[route1, route2, route3])
        self.provider.add_interface(interface)

        self.provider.apply()

        #route_data = utils.get_file_data(self.temp_route_file.name)
        #self.assertEqual(_ROUTES, route_data)

    def test_dhcp_ovs_bridge_network_apply(self):
        interface = objects.Interface('em1')
        bridge = objects.OvsBridge('br-ctlplane', use_dhcp=True,
                                   members=[interface])
        self.provider.add_interface(interface)
        self.provider.add_bridge(bridge)
        self.provider.apply()

    def test_dhclient_stop_on_iface_activate(self):
        self.stop_dhclient_interfaces = []
        v4_addr = objects.Address('192.168.1.2/24')
        interface = objects.Interface('em1', addresses=[v4_addr])
        interface2 = objects.Interface('em2', use_dhcp=True)
        interface3 = objects.Interface('em3', use_dhcp=False)
        self.provider.add_interface(interface)
        self.provider.add_interface(interface2)
        self.provider.add_interface(interface3)
        self.provider.apply()
        # stop dhclient on em1 due to static IP and em3 due to no IP
        self.assertIn('em1', self.stop_dhclient_interfaces)
        self.assertIn('em3', self.stop_dhclient_interfaces)
        self.assertNotIn('em2', self.stop_dhclient_interfaces)

    def test_apply_noactivate(self):
        interface = objects.Interface('em1')
        bridge = objects.OvsBridge('br-ctlplane', use_dhcp=True,
                                   members=[interface])
        self.provider.add_interface(interface)
        self.provider.add_bridge(bridge)
        self.provider.apply(activate=False)
        self.assertEqual([], self.ifup_interface_names)

    def test_bond_active_slave(self):
        # setup and apply a bond
        interface1 = objects.Interface('em1')
        interface2 = objects.Interface('em2', primary=True)
        bond = objects.OvsBond('bond1', use_dhcp=True,
                               members=[interface1, interface2])
        self.provider.add_interface(interface1)
        self.provider.add_interface(interface2)
        self.provider.add_bond(bond)
        self.provider.apply()
        ovs_appctl_cmds = '/bin/ovs-appctl bond/set-active-slave bond1 em2'
        self.assertIn(ovs_appctl_cmds, self.ovs_appctl_cmds)

    def test_bond_active_ordering(self):
        # setup and apply a bond
        interface1 = objects.Interface('em1')
        interface2 = objects.Interface('em2')
        bond = objects.OvsBond('bond1', use_dhcp=True,
                               members=[interface1, interface2])
        self.provider.add_interface(interface1)
        self.provider.add_interface(interface2)
        self.provider.add_bond(bond)
        self.provider.apply()
        ovs_appctl_cmds = '/bin/ovs-appctl bond/set-active-slave bond1 em1'
        self.assertIn(ovs_appctl_cmds, self.ovs_appctl_cmds)

    def test_ifcfg_route_commands(self):

        tmpdir = tempfile.mkdtemp()
        interface = "eth0"
        interface_filename = tmpdir + '/route-' + interface
        file = open(interface_filename, 'w')
        file.write(_IFCFG_ROUTES1)
        file.close()

        # Changing only the routes should delete and add routes
        command_list1 = ['route del default via 192.0.2.1 dev eth0',
                         'route del 192.0.2.1/24 via 192.0.2.1 dev eth0',
                         'route add default via 192.0.1.1 dev eth0',
                         'route add 192.0.1.1/24 via 192.0.3.1 dev eth1']
        #commands = self.provider.iproute2_route_commands(interface_filename,
        #                                                 _IFCFG_ROUTES2)
        #self.assertTrue(commands == command_list1)

    def test_vlan_apply(self):
        vlan = objects.Vlan('em1', 5)
        self.provider.add_vlan(vlan)
        self.provider.apply()

        self.assertEqual(0, len(self.provider.errors))
        self.assertEqual(yaml.safe_load(_VLAN_NO_IP)[0],
                         self.provider.vlan_data['vlan5'])

    def test_cleanup(self):
        self.provider.apply(cleanup=True)
        self.assertTrue(not os.path.exists(self.temp_cleanup_file.name))

    def test_cleanup_not_loopback(self):
        tmp_lo_file = '%s-lo' % self.temp_cleanup_file.name
        utils.write_config(tmp_lo_file, 'foo')

        def test_cleanup_pattern():
            return '%s-*' % self.temp_cleanup_file.name
        self.stub_out('os_net_config.impl_nmstate.cleanup_pattern',
                      test_cleanup_pattern)

        self.provider.apply(cleanup=True)
        self.assertTrue(os.path.exists(tmp_lo_file))
        os.remove(tmp_lo_file)

    def test_ovs_restart_not_called(self):
        interface = objects.Interface('em1')
        execute_strings = []

        def test_execute(*args, **kwargs):
            execute_strings.append(args[1])
        self.stub_out('os_net_config.NetConfig.execute', test_execute)

        self.provider.noop = True
        self.provider.add_interface(interface)
        self.provider.apply()
        self.assertNotIn('Restart openvswitch', execute_strings)

    def _failed_netapplier_apply(self, state, verify=True):
        raise netapplier.NmstateVerificationError('Test Error')

    def test_set_iface_failure(self):
        self.stub_out('libnmstate.netapplier.apply',
                      self._failed_netapplier_apply)
        v4_addr = objects.Address('192.168.1.2/24')
        interface = objects.Interface('em1', addresses=[v4_addr])
        self.provider.add_interface(interface)

        self.assertRaises(os_net_config.ConfigurationError,
                          self.provider.apply)

    def test_set_iface_failure_multiple(self):
        self.stub_out('libnmstate.netapplier.apply',
                      self._failed_netapplier_apply)
        v4_addr = objects.Address('192.168.1.2/24')
        interface = objects.Interface('em1', addresses=[v4_addr])
        v4_addr2 = objects.Address('192.168.2.2/24')
        interface2 = objects.Interface('em2', addresses=[v4_addr2])
        self.provider.add_interface(interface)
        self.provider.add_interface(interface2)

        self.assertRaises(os_net_config.ConfigurationError,
                          self.provider.apply)

