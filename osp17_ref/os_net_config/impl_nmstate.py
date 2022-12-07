# -*- coding: utf-8 -*-

# Copyright 2014-2015 Red Hat, Inc.
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

import glob
import json
import logging
import netaddr
import os
import re

import os_net_config
from os_net_config import objects
from os_net_config import utils

try:
    import libnmstate
except ModuleNotFoundError: pass    
#except ModuleNotFoundError as e:
#    if str(e) == "No module named 'libnmstate'":
#        msg = 'Error loading libnmstate package, is it installed?'
#        raise RuntimeError(msg)

from libnmstate import netapplier
from libnmstate import netinfo
from libnmstate.schema import Bond
from libnmstate.schema import Interface
from libnmstate.schema import InterfaceIPv4
from libnmstate.schema import InterfaceIPv6
from libnmstate.schema import InterfaceState
from libnmstate.schema import InterfaceType
from libnmstate.schema import OVSBridge
from libnmstate.schema import Route as RouteSchema
from libnmstate.schema import VLAN


logger = logging.getLogger(__name__)

# Import the raw NetConfig object so we can call its methods
netconfig = os_net_config.NetConfig()


IPV4_DEFAULT_GATEWAY_DESTINATION = "0.0.0.0/0"
IPV6_DEFAULT_GATEWAY_DESTINATION = "::/0"


def is_dict_subset(superset, subset):
    """Check to see if one dict is a subset of another dict."""

    if superset == subset:
        return True
    if superset and subset:
        for key, value in subset.items():
            if key not in superset:
                return False
            if isinstance(value, dict):
                if not is_dict_subset(superset[key], value):
                    return False
            elif isinstance(value, str):
                if value not in superset[key]:
                    return False
            elif isinstance(value, list):
                try:
                    if not set(value) <= set(superset[key]):
                        return False
                except TypeError:
                    for item in value:
                        if item not in superset[key]:
                            return False
            elif isinstance(value, set):
                if not value <= superset[key]:
                    return False
            else:
                if not value == superset[key]:
                    return False
        return True
    return False


class NmstateNetConfig(os_net_config.NetConfig):
    """Configure network interfaces using NetworkManager via nmstate API."""

    def __init__(self, noop=False, root_dir=''):
        super(NmstateNetConfig, self).__init__(noop, root_dir)
        self.interface_data = {}
        self.vlan_data = {}
        self.route_data = {}
        self.route6_data = {}
        self.bridge_data = {}
        self.linuxbond_data = {}
        self.linuxteam_data = {}
        self.ovs_port_data = {}
        self.member_names = {}
        self.renamed_interfaces = {}
        self.bond_primary_ifaces = {}
        self.ovs_commands = {}
        self.nmcli_commands = {}
        logger.info('nmstate net config provider created.')

    def iface_state(self, name=''):
        """Return the current interface state according to nmstate.

        Return the current state of all interfaces, or the named interface.
        :param name: name of the interface to return state, otherwise all.
        :returns: list of all interfaces, or those matching name if specified
        """
        ifaces = netinfo.show_running_config()[Interface.KEY]
        logger.info('----------------------------')
        logger.info('List of ifaces running config %s' % ifaces)
        if name != "":
            return list(x for x in ifaces if x['name'] == name)
        else:
            return ifaces

    def route_state(self, name=''):
        """Return the current routes set according to nmstate.

        Return the current routes for all interfaces, or the named interface.
        :param name: name of the interface to return state, otherwise all.
        :returns: list of all interfaces, or those matching name if specified
        """

        routes = netinfo.show_running_config()[RouteSchema.KEY][RouteSchema.CONFIG]
        logger.info('----------------------------')
        logger.info('List of routes running config %s' % routes)
        if name != "":
            return list(x for x in routes if x[RouteSchema.NEXT_HOP_INTERFACE] == name)
        else:
            return routes


    def config_state(self):
        """Return the current stored network configuration according to nmstate

        Return the current stored state of the network as NetworkManager sees
        it, as rendered by nmstate. This is equivalent to """

    def set_ifaces(self, iface_data, verify=True):
        """Apply the desired state using nmstate.

        :param iface_data: interface config json
        :param verify: boolean that determines if config will be verified
        """
        state = {Interface.KEY: iface_data}
        state_dmp = json.dumps(state, indent=4, sort_keys=True)
        logger.debug('Applying interface config with nmstate: %s' % state_dmp)
        netapplier.apply(state, verify_change=verify)

    def set_routes(self, route_data, verify=True):
        """Apply the desired routes using nmstate.

        :param route_data: interface config json
        :param verify: boolean that determines if config will be verified
        """

        state = {RouteSchema.KEY: {RouteSchema.CONFIG: route_data}}
        state_dmp = json.dumps(state, indent=4, sort_keys=True)
        logger.debug('Applying routes with nmstate: %s' % state_dmp)
        netapplier.apply(state, verify_change=verify)

    def child_members(self, name):
        children = set()
        try:
            for member in self.member_names[name]:
                children.add(member)
                children.update(self.child_members(member))
        except KeyError:
            pass
        return children

    def _add_common(self, base_opt):

        if not base_opt.name in self.nmcli_commands:
            self.nmcli_commands[base_opt.name] = []
        # TODO(dsneddon): NetworkManager does not yet support OVS extra.
        ovs_extra = []
        data = {Interface.IPV4: {InterfaceIPv4.ENABLED: False},
                Interface.IPV6: {InterfaceIPv6.ENABLED: False},
                Interface.NAME: base_opt.name}
        if base_opt.use_dhcp:
            data[Interface.IPV4][InterfaceIPv4.ENABLED] = True
            data[Interface.IPV4][InterfaceIPv4.DHCP] = True
        else:
            data[Interface.IPV4][InterfaceIPv4.DHCP] = False
        if base_opt.use_dhcpv6:
            data[Interface.IPV6][InterfaceIPv6.ENABLED] = True
            data[Interface.IPV6][InterfaceIPv6.DHCP] = True
        else:
            data[Interface.IPV6][InterfaceIPv6.DHCP] = False
        # NetworkManager always starts on boot, so set enabled state instead
        if base_opt.onboot:
            data[Interface.STATE] = InterfaceState.UP
        else:
            data[Interface.STATE] = InterfaceState.DOWN
        if isinstance(base_opt, objects.Interface) and not base_opt.hotplug:
            logger.info('Using NetworkManager, hotplug is always set to true.')
        if not base_opt.nm_controlled:
            logger.info('Using NetworkManager, nm_controlled is always true.')
        if base_opt.dns_servers and not base_opt.use_dhcp:
            data[Interface.IPV4][InterfaceIPv4.AUTO_DNS] = False
        if isinstance(base_opt, objects.Interface):
            data[Interface.TYPE] = InterfaceType.ETHERNET
            if base_opt.ethtool_opts:
                # TODO(dsneddon): Implement when nmstate supports ethtool opts
                # https://nmstate.atlassian.net/browse/NMSTATE-27
                pass
        if isinstance(base_opt, objects.OvsInterface):
            data[Interface.TYPE] = InterfaceType.OVS_INTERFACE
            data[Interface.STATE] = InterfaceState.UP
        if isinstance(base_opt, objects.Vlan) or re.match(r'\w+\.\d+$',
                                                          base_opt.name):
            if not base_opt.ovs_port:
                # vlans on OVS bridges are internal ports (no device, etc)
                data[Interface.TYPE] = InterfaceType.VLAN
                data[VLAN.CONFIG_SUBTREE] = {}
                if isinstance(base_opt, objects.Vlan):
                    # data['vlan']['id'] = base_opt.vlan_id
                    data[VLAN.CONFIG_SUBTREE][VLAN.ID] = base_opt.vlan_id
                    if base_opt.device:
                        data[VLAN.CONFIG_SUBTREE] = {
                            VLAN.ID: base_opt.vlan_id,
                            VLAN.BASE_IFACE: base_opt.device
                        }
                    elif base_opt.linux_bond_name:
                        data[VLAN.CONFIG_SUBTREE] = {
                            VLAN.ID: base_opt.vlan_id,
                            VLAN.BASE_IFACE: base_opt.linux_bond_name
                        }
                else:
                    data[VLAN.CONFIG_SUBTREE] = {
                        VLAN.ID: int(base_opt.name.split('.')[1]),
                        VLAN.BASE_IFACE: base_opt.name.split('.')[0]
                    }
        elif isinstance(base_opt, objects.IvsInterface):
            msg = 'Error: IVS interfaces not yet supported by impl_nmstate'
            raise os_net_config.NotImplemented(msg)
        elif isinstance(base_opt, objects.NfvswitchInternal):
            msg = 'Error: NFVSwitch not yet supported by impl_nmstate'
            raise os_net_config.NotImplemented(msg)
        elif isinstance(base_opt, objects.IbInterface):
            msg = 'Error: Infiniband not yet supported by impl_nmstate'
            raise os_net_config.NotImplemented(msg)
        if base_opt.linux_bond_name:
            # TODO(dsneddon): Figure out how to handle Bond master relationship
            #     It seems base interfaces probably don't specify master
            pass
        if base_opt.linux_team_name:
            # TODO(dsneddon): Figure out how to handle Team master relationship
            #     It seems base interfaces probably don't specify master
            pass
        if base_opt.ovs_port:
            if base_opt.bridge_name:
                data[Interface.STATE] = InterfaceState.UP
                if (isinstance(base_opt, objects.Vlan) or
                        isinstance(base_opt, objects.OvsInterface)):
                    data[Interface.TYPE] = InterfaceType.OVS_INTERFACE
                else:
                    data[Interface.TYPE] = InterfaceType.ETHERNET
        if base_opt.linux_bridge_name:
            # TODO(dsneddon): Implement linux bridge
            pass
        if isinstance(base_opt, objects.OvsBridge):
            if base_opt.name not in self.ovs_commands:
                self.ovs_commands[base_opt.name] = []
            data[Interface.TYPE] = 'ovs-bridge'
            # address bits can't be on the ovs-bridge
            del data[Interface.IPV4]
            del data[Interface.IPV6]
            data[OVSBridge.CONFIG_SUBTREE] = {
                OVSBridge.OPTIONS_SUBTREE: {
                     OVSBridge.Options.FAIL_MODE: base_opt.fail_mode,
                     OVSBridge.Options.MCAST_SNOOPING_ENABLED: False,
                     OVSBridge.Options.RSTP: False,
                     OVSBridge.Options.STP: False
                },
                OVSBridge.PORT_SUBTREE: []
            }
            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
                bps = []
                for member in members:
                    if member.startswith('vlan'):
                        vlan_id = int(member.strip('vlan'))
                        port = {
                            OVSBridge.Port.NAME: member,
                            OVSBridge.Port.VLAN_SUBTREE: {
                                OVSBridge.Port.Vlan.MODE: 'access',
                                OVSBridge.Port.Vlan.TAG: vlan_id
                            }
                        }
                        bps.append(port)
                    else:
                        port = {'name': member}
                        bps.append(port)
                ovs_port_name = "%s-p" % base_opt.name
                port = {'name': ovs_port_name}
                bps.append(port)
                data[OVSBridge.CONFIG_SUBTREE][OVSBridge.PORT_SUBTREE] = bps
            if base_opt.primary_interface_name:
                mac = utils.interface_mac(base_opt.primary_interface_name)
                data[Interface.MAC] = mac
            # TODO(dsneddon): Implement extracting ovs_extra into nmstate params
            ovs_extra.extend(base_opt.ovs_extra)
        elif isinstance(base_opt, objects.OvsUserBridge):
            # TODO(dsneddon): Implement DPDK user bridges
            msg = "Error: OVS User bridges not yet supported by impl_nmstate"
            raise os_net_config.NotImplemented(msg)
        elif isinstance(base_opt, objects.OvsBond):
            # TODO(dsneddon): Implement OVS bonds
            data[Interface.TYPE] = "ovs-bond"
            if base_opt.primary_interface_name:
                primary_name = base_opt.primary_interface_name
                self.bond_primary_ifaces[base_opt.name] = primary_name
            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
            ovs_extra.extend(base_opt.ovs_extra)
        elif isinstance(base_opt, objects.LinuxBridge):
            # TODO(dsneddon): Implement when nmstate supports Linux bridges
            #     https://nmstate.atlassian.net/browse/NMSTATE-9
            msg = "Error: Linux bridges are not yet supported by impl_nmstate"
            raise os_net_config.NotImplemented(msg)
        elif isinstance(base_opt, objects.LinuxBond):
            data[Interface.TYPE] = InterfaceType.BOND
            data[Interface.STATE] = InterfaceState.UP
            # Bond.CONFIG_SUBTREE == 'link-aggregation'
            data[Bond.CONFIG_SUBTREE] = {
                Bond.MODE: "active-backup",
                Bond.PORT: [],
                Bond.OPTIONS_SUBTREE: {}
            }
            if base_opt.primary_interface_name:
                pass
                # TODO(dsneddon): Figure out how to set primary bond interface
                #primary_name = base_opt.primary_interface_name
                #if 'options' not in data['link-aggregation']:
                #    data['link-aggregation']['options'] = {}
                #data['link-aggregation']['options']['primary'] = primary_name

            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
                data[Bond.CONFIG_SUBTREE][Bond.PORT] = members
            if base_opt.bonding_options:
                # TODO(dsneddon): Split bonding_options into key/value pairs
                if Bond.OPTIONS_SUBTREE not in [Bond.CONFIG_SUBTREE]:
                    data[Bond.CONFIG_SUBTREE][Bond.OPTIONS_SUBTREE] = {}
                options = re.findall(r'(.+?)=(.+?)($|\s)',
                                     base_opt.bonding_options)
                for option in options:
                    if option[0] == Bond.MODE or option[0] == 'MODE':
                        data[Bond.CONFIG_SUBTREE][Bond.MODE] = option[1]
                    else:
                        # Apply key/value pairs, hopefully nmstate supports key
                        data[Bond.CONFIG_SUBTREE][option[0]] = option[1]
        elif isinstance(base_opt, objects.LinuxTeam):
            # TODO(dsneddon): If to be supported, convert to nmstate API format
            data['type'] = 'team'
            if base_opt.primary_interface_name:
                if 'options' not in data['link-aggregation']:
                    data['link-aggregatino']['options'] = {}
                primary_name = base_opt.primary_interface_name
                data['link-aggregation']['options']['primary'] = primary_name
            if base_opt.use_dhcp:
                data['ipv4']['dhcp'] = True
            if base_opt.members:
                members = [member.name for member in base_opt.members]
                self.member_names[base_opt.name] = members
                data['slaves'].extend(members)
            if base_opt.bonding_options:
                try:
                    data['options'] = json.loads(base_opt.bonding_options)
                except Exception as e:
                    msg = "JSON error in team bonding_options:\n%s" % e
                    raise os_net_config.ConfigurationError(msg)
                msg = json.dumps(json.loads(base_opt.bonding_options))
                logger.debug("%s options: %s") % (base_opt.name, msg)
                # Populate defaults in not specified
                if 'runner' not in data['options']:
                    data['options']['runner'] = {'name': 'activebackup'}
                if 'link-watch' not in data['options']:
                    data['options']['link-watch'] = {'name': 'ethtool'}
        elif isinstance(base_opt, objects.OvsTunnel):
            # TODO(dsneddon): Implement when nmstate supports OVS tunnel ports:
            #     https://nmstate.atlassian.net/browse/NMSTATE-135
            msg = "Error: OVS tunnels not yet supported by impl_nmstate"
            raise os_net_config.NotImplemented(msg)
        elif isinstance(base_opt, objects.OvsPatchPort):
            # TODO(dsneddon): Implement when nmstate supports OVS patch ports:
            #       https://nmstate.atlassian.net/browse/NMSTATE-136
            msg = "Error: OVS tunnels not yet supported by impl_nmstate"
            raise os_net_config.NotImplemented(msg)
        elif isinstance(base_opt, objects.OvsDpdkPort):
            # TODO(dsneddon): Implement nmstate support for OVS DPDK:
            msg = "Error: OVS DPDK ports not yet supported by impl_nmstate"
            raise os_net_config.NotImplemented(msg)
        elif isinstance(base_opt, objects.OvsDpdkBond):
            # TODO(dsneddon): Implement nmstate support for OVS DPDK bonds:
            msg = "Error: OVS DPDK bonds not yet supported by impl_nmstate"
            raise os_net_config.NotImplemented(msg)

        if base_opt.mtu:
            data[Interface.MTU] = base_opt.mtu
        if base_opt.addresses:
            v4_addresses = base_opt.v4_addresses()
            if v4_addresses:
                for address in v4_addresses:
                    netmask_ip = netaddr.IPAddress(address.netmask)
                    ip_netmask = {'ip': address.ip,
                                  'prefix-length': netmask_ip.netmask_bits()}
                    if InterfaceIPv4.ADDRESS not in data[Interface.IPV4]:
                        data[Interface.IPV4][InterfaceIPv4.ADDRESS] = []
                    data[Interface.IPV4][InterfaceIPv4.ENABLED] = True
                    data[Interface.IPV4][InterfaceIPv4.ADDRESS].append(ip_netmask)
            v6_addresses = base_opt.v6_addresses()
            if v6_addresses:
                data[Interface.IPV6]['autoconf'] = False
                for v6_address in v6_addresses:
                    netmask_ip = netaddr.IPAddress(v6_address.netmask)
                    v6ip_netmask = {'ip': v6_address.ip,
                                    'prefix-length': netmask_ip.netmask_bits()}
                    if InterfaceIPv6.ADDRESS not in data[Interface.IPV6]:
                        data[Interface.IPV6][InterfaceIPv6.ADDRESS] = []
                    data[Interface.IPV6][InterfaceIPv6.ENABLED] = True
                    data[Interface.IPV6][InterfaceIPv6.ADDRESS].append(v6ip_netmask)

        if base_opt.hwaddr:
            # TODO(dsneddon): Fix when nmstate supports setting MAC
            command = "con modify %s 802-3-ethernet.cloned-mac-address %s"
            self.nmcli_commands[base_opt.name].append(command)
            msg = "Setting MAC address not supported in impl_nmstate, ignoring"
            logger.error(msg)
            pass
        if ovs_extra:
            if base_opt.name not in self.ovs_commands:
                self.ovs_commands[base_opt.name] = []
                self.ovs_commands[base_opt.name].extend(ovs_extra)
        if not base_opt.defroute:
            data['ipv4']['auto-gateway'] = False
        if base_opt.dhclient_args:
            msg = "DHCP Client args not supported in impl_nmstate, ignoring"
            logger.error(msg)
        if base_opt.dns_servers:
            servers = ",".join(base_opt.dns_servers)
            command = "con modify %s ipv4.dns %s" % (base_opt.name, servers)
            self.nmcli_commands[base_opt.name].append(command)
        if base_opt.rules:
            msg = "IP rules args not supported in impl_nmstate, ignoring"
            logger.error(msg)
        return data


    def _add_routes(self, interface_name, routes=[]):
        logger.info('adding custom route for interface: %s' % interface_name)

        routes_data = []
        data = ""
        first_line = ""
        data6 = ""
        first_line6 = ""
        for route in routes:
            route_data = {}
            options = ""
            if route.metric:
                route_data[RouteSchema.METRIC] = route.metric
            if route.ip_netmask:
                route_data[RouteSchema.DESTINATION] = route.ip_netmask
            if route.next_hop:
                route_data[RouteSchema.NEXT_HOP_ADDRESS] = route.next_hop
                route_data[RouteSchema.NEXT_HOP_INTERFACE] = interface_name
                if route.default:
                    if ":" in route.next_hop:
                        route_data[RouteSchema.DESTINATION] = IPV6_DEFAULT_GATEWAY_DESTINATION
                    else:
                        route_data[RouteSchema.DESTINATION] = IPV4_DEFAULT_GATEWAY_DESTINATION

            if route.route_table:
                route_data[RouteSchema.TABLE_ID] = route.route_table

            routes_data.append(route_data)

        self.route_data[interface_name] = routes_data
        logger.debug('route data: %s' % self.route_data[interface_name])

    def add_interface(self, interface):
        """Add an Interface object to the net config object.

        :param interface: The Interface object to add.
        """
        logger.info('adding interface: %s' % interface.name)
        data = self._add_common(interface)
        logger.debug('interface data: %s' % data)
        self.interface_data[interface.name] = data
        if interface.routes:
            self._add_routes(interface.name, interface.routes)

        if interface.renamed:
            logger.info("Interface %s being renamed to %s"
                        % (interface.hwname, interface.name))
            self.renamed_interfaces[interface.hwname] = interface.name

    def add_vlan(self, vlan):
        """Add a Vlan object to the net config object.

        :param vlan: The vlan object to add.
        """
        logger.info('adding vlan: %s' % vlan.name)
        data = self._add_common(vlan)
        logger.debug('vlan data: %s' % data)
        self.vlan_data[vlan.name] = data
        if vlan.routes:
            self._add_routes(vlan.name, vlan.routes)

    def add_bridge(self, bridge):
        """Add an OvsBridge object to the net config object.

        :param bridge: The OvsBridge object to add.
        """
        ovs_port_name = "%s-p" % bridge.name
        ovs_interface_port = objects.OvsInterface (ovs_port_name,
                 use_dhcp=bridge.use_dhcp, use_dhcpv6=bridge.use_dhcpv6,
                 addresses=bridge.addresses,  routes=bridge.routes,
                 rules=bridge.rules, mtu=bridge.mtu, primary=False,
                 nic_mapping=None,
                 persist_mapping=None, defroute=bridge.defroute,
                 dhclient_args=bridge.dhclient_args, dns_servers=bridge.dns_servers,
                 nm_controlled=None, onboot=bridge.onboot,
                 domain=bridge.domain)


        logger.info('Adding ovs interface port %s' % ovs_interface_port.name)
        data = self._add_common(ovs_interface_port)
        logger.debug('iface port data: %s' % data)
        self.bridge_data[ovs_interface_port.name] = data


        logger.info('adding bridge: %s' % bridge.name)
        data = self._add_common(bridge)
        logger.debug('bridge data: %s' % data)
        self.bridge_data[bridge.name] = data
        if ovs_interface_port.routes:
            self._add_routes(bridge.name, bridge.routes)

    def add_linux_bridge(self, bridge):
        """Add a LinuxBridge object to the net config object.

        :param bridge: The LinuxBridge object to add.
        """
        logger.info('adding linux bridge: %s' % bridge.name)
        data = self._add_common(bridge)
        logger.debug('bridge data: %s' % data)
        self.linuxbridge_data[bridge.name] = data
        if bridge.routes:
            self._add_routes(bridge.name, bridge.routes)

    def add_bond(self, bond):
        """Add an OvsBond object to the net config object.

        :param bond: The OvsBond object to add.
        """
        logger.info('adding bond: %s' % bond.name)
        data = self._add_common(bond)
        logger.debug('bond data: %s' % data)
        self.interface_data[bond.name] = data
        if bond.routes:
            self._add_routes(bond.name, bond.routes)

    def add_linux_bond(self, bond):
        """Add a LinuxBond object to the net config object.

        :param bond: The LinuxBond object to add.
        """
        logger.info('adding linux bond: %s' % bond.name)
        data = self._add_common(bond)
        logger.debug('bond data: %s' % data)
        self.linuxbond_data[bond.name] = data
        if bond.routes:
            self._add_routes(bond.name, bond.routes)

    def add_linux_team(self, team):
        """Add a LinuxTeam object to the net config object.

        :param team: The LinuxTeam object to add.
        """
        logger.info('adding linux team: %s' % team.name)
        data = self._add_common(team)
        logger.debug('team data: %s' % data)
        self.linuxteam_data[team.name] = data
        if team.routes:
            self._add_routes(team.name, team.routes)

    def apply(self, cleanup=False, activate=True):
        """Apply the network configuration.

        :param cleanup: A boolean which indicates whether any undefined
            (existing but not present in the object model) interface
            should be disabled and deleted.
        :param activate: A boolean which indicates if the config should
            be activated by stopping/starting interfaces
            NOTE: if cleanup is specified we will deactivate interfaces even
            if activate is false
        :returns: a dict of the format: filename/data which contains info
            for each file that was changed (or would be changed if in --noop
            mode).
        Note the noop mode is set via the constructor noop boolean
        """
        logger.info('applying network configs...')
        apply_vlans = []
        apply_linux_bonds = []
        apply_linux_teams = []
        apply_interfaces = []
        restart_interfaces = []
        apply_bridges = []
        apply_routes = []
        update_files = {}
        all_file_names = []
        stop_dhclient_interfaces = []
        ovs_needs_restart = False

        for interface_name, iface_data in self.interface_data.items():
            routes_data = self.route_data.get(interface_name, '')
            iface_state = self.iface_state(interface_name)
            curr_routes = self.route_state(interface_name)
            if not is_dict_subset(iface_state, iface_data):
                apply_interfaces.append((interface_name, iface_data))
            else:
                logger.info('No changes required for interface: %s' %
                            interface_name)
            logger.info('Routes_data %s' % routes_data)
            for route_data in routes_data:
                if not is_dict_subset(curr_routes, route_data):
                    apply_routes.append(route_data)
                else:
                    logger.info('No changes required for routes to %s' %
                                interface_name)

        for bridge_name, bridge_data in self.bridge_data.items():
            route_data = self.route_data.get(bridge_name, '')
            bridge_state = self.iface_state(bridge_name)
            curr_routes = self.route_state(bridge_name)
            if not is_dict_subset(bridge_state, bridge_data):
                apply_bridges.append((bridge_name, bridge_data))
            else:
                logger.info('No changes required for bridge: %s' %
                            bridge_name)
            for route_data in routes_data:
                if not is_dict_subset(curr_routes, route_data):
                    apply_routes.append(route_data)
                else:
                    logger.info('No changes required for routes to %s' %
                                bridge_name)

        for team_name, team_data in self.linuxteam_data.items():
            route_data = self.route_data.get(team_name, '')
            route6_data = self.route6_data.get(team_name, '')
            team_route_path = self.root_dir + route_config_path(team_name)
            team_route6_path = self.root_dir + route6_config_path(team_name)
            team_state = self.iface_state(team_name)
            all_file_names.append(team_route_path)
            all_file_names.append(team_route6_path)
            if not is_dict_subset(team_state, team_data):
                apply_linux_teams.append((team_name, team_data))
                if 'ipv4' in team_data and 'dhcp' in team_data['ipv4']:
                    if str(team_data['ipv4']['dhcp']) == 'False':
                        stop_dhclient_interfaces.append(team_name)
                else:
                    stop_dhclient_interfaces.append(team_name)
            else:
                logger.info('No changes required for linux team: %s' %
                            team_name)
            if utils.diff(team_route_path, route_data):
                update_files[team_route_path] = route_data
                apply_routes.append((team_name, route_data))
            if utils.diff(team_route6_path, route6_data):
                update_files[team_route6_path] = route6_data
                apply_routes.append((team_name, route6_data))

        for bond_name, bond_data in self.linuxbond_data.items():
            route_data = self.route_data.get(bond_name, '')
            route6_data = self.route6_data.get(bond_name, '')
            bond_route_path = self.root_dir + route_config_path(bond_name)
            bond_route6_path = self.root_dir + route6_config_path(bond_name)
            bond_state = self.iface_state(bond_name)
            all_file_names.append(bond_route_path)
            all_file_names.append(bond_route6_path)
            if not is_dict_subset(bond_state, bond_data):
                apply_linux_bonds.append((bond_name, bond_data))
                if 'ipv4' in bond_data and 'dhcp' in bond_data['ipv4']:
                    if str(bond_data['ipv4']['dhcp']) == 'False':
                        stop_dhclient_interfaces.append(bond_name)
                else:
                    stop_dhclient_interfaces.append(bond_name)
            else:
                logger.info('No changes required for linux bond: %s' %
                            bond_name)
            if utils.diff(bond_route_path, route_data):
                update_files[bond_route_path] = route_data
                apply_routes.append((bond_name, route_data))
            if utils.diff(bond_route6_path, route6_data):
                update_files[bond_route6_path] = route6_data
                apply_routes.append((bond_name, route6_data))

        # NOTE(hjensas): Process the VLAN's last so that we know if the vlan's
        # parent interface is being restarted.
        for vlan_name, vlan_data in self.vlan_data.items():
            route_data = self.route_data.get(vlan_name, '')
            route6_data = self.route6_data.get(vlan_name, '')
            vlan_state = self.iface_state(vlan_name)
            vlan_route_path = self.root_dir + route_config_path(vlan_name)
            vlan_route6_path = self.root_dir + route6_config_path(vlan_name)
            all_file_names.append(vlan_route_path)
            all_file_names.append(vlan_route6_path)
            if not is_dict_subset(vlan_state, vlan_data):
                apply_vlans.append((vlan_name, vlan_data))
                if 'ipv4' in vlan_data and 'dhcp' in vlan_data['ipv4']:
                    if str(vlan_data['ipv4']['dhcp']) == 'False':
                        stop_dhclient_interfaces.append(vlan_name)
                else:
                    stop_dhclient_interfaces.append(vlan_name)
            else:
                logger.info('No changes required for vlan interface: %s' %
                            vlan_name)
            if utils.diff(vlan_route_path, route_data):
                update_files[vlan_route_path] = route_data
                apply_routes.append((vlan_name, route_data))
            if utils.diff(vlan_route6_path, route6_data):
                update_files[vlan_route6_path] = route6_data
                apply_routes.append((vlan_name, route6_data))

        if cleanup:
            for ifcfg_file in glob.iglob(cleanup_pattern()):
                if ifcfg_file not in all_file_names:
                    interface_name = ifcfg_file[len(cleanup_pattern()) - 1:]
                    if interface_name != 'lo':
                        logger.info('cleaning up interface: %s'
                                    % interface_name)
                        self.ifdown(interface_name)
                        self.remove_config(ifcfg_file)

        if activate:
            interfaces = []
            for bridge in apply_bridges:
                interfaces.append(bridge[1])
                # logger.debug('Running nmstate to configure bridge: %s' %
                #              bridge[0])
                # if not self.noop:
                #     try:
                #         self.set_ifaces(bridge[0], bridge[1])
                #     except Exception as e:
                #         logger.error('Error setting state on bridge %s: %s' %
                #                      (bridge[0], str(e)))
                #         self.errors.append(e)

            for interface in apply_interfaces:
                interfaces.append(interface[1])
                # logger.debug('Running nmstate to configure interface %s' %
                #              interface[0])
                # if not self.noop:
                #     try:
                #         self.set_ifaces(interface[0], interface[1])
                #     except Exception as e:
                #         logger.error(
                #             'Error setting state on interface %s: %s' %
                #             (interface[0], str(e)))
                #         self.errors.append(e)

            for vlan in apply_vlans:
                interfaces.append(vlan[1])
                logger.debug('Running nmstate to configure vlan %s' % vlan[0])
                if not self.noop:
                    try:
                        self.set_ifaces(vlan[0], vlan[1])
                    except Exception as e:
                        msg = 'Error setting VLAN %s state: %s' % (vlan[0],
                                                                   str(e))
                        raise os_net_config.ConfigurationError(msg)

            for linux_bond in apply_linux_bonds:
                interfaces.append(linux_bond[1])
                # logger.debug('Running nmstate to configure linux bond %s' %
                #              linux_bond[0])
                # if not self.noop:
                #     try:
                #         self.set_ifaces(linux_bond[0], linux_bond[1])
                #     except Exception as e:
                #         logger.error(
                #             'Error setting state on linux bond %s: %s' %
                #             (linux_bond[0], str(e)))
                #         self.errors.append(e)

            for linux_team in apply_linux_teams:
                interfaces.append(linux_team[1])
                # logger.debug('Running nmstate to configure linux team %s' %
                #              linux_team[0])
                # if not self.noop:
                #     try:
                #         self.set_ifaces(linux_team[0], linux_team[1])
                #     except Exception as e:
                #         logger.error(
                #             'Error setting state on linux team %s: %s' %
                #             (linux_team[0], str(e)))
                #         self.errors.append(e)

            if not self.noop:
                try:
                    self.set_ifaces(interfaces)
                except Exception as e:
                    msg = 'Error setting interfaces state: %s' % str(e)
                    raise os_net_config.ConfigurationError(msg)


            if not self.noop:
                try:
                    self.set_routes(apply_routes)
                except Exception as e:
                    msg = 'Error setting interfaces state: %s' % str(e)
                    raise os_net_config.ConfigurationError(msg)
            # TODO(Karthik)
            #    logger.debug('Applying routes for interface %s' % interface[0])
            #    filename = self.root_dir + route_config_path(interface[0])
            #    commands = self.iproute2_route_commands(filename, interface[1])
            #    for command in commands:
            #        args = command.split()
            #        try:
            #            if len(args) > 0:
            #                if not self.noop:
            #                    self.execute('Running ip %s' % command,
            #                                 command, *args)
            #        except Exception as e:
            #            logger.warning("Error in 'ip %s', restarting %s:\n%s" %
            #                           (command, interface[0], str(e)))
            #            restart_interfaces.append(interface[0])
            #            restart_interfaces.extend(
            #                self.child_members(interface[0]))
            #            break

            for oldname, newname in self.renamed_interfaces.items():
                self.ifrename(oldname, newname)

            # TODO(dsneddon): implement when nmstate supports DPDK
            # DPDK initialization is done before running os-net-config, to make
            # the DPDK ports available when enabled. DPDK Hotplug support is
            # supported only in OvS 2.7 version. Until then, OvS needs to be
            # restarted after adding a DPDK port. This change will be removed
            # on migration to OvS 2.7 where DPDK Hotplug support is available.
            if ovs_needs_restart:
                msg = 'Restart openvswitch'
                self.execute(msg, '/usr/bin/systemctl',
                             'restart', 'openvswitch')

        for location, data in update_files.items():
            self.write_config(location, data)

        if activate:
            for interface in restart_interfaces:
                if not self.noop:
                    self.ifdown(interface)

            # If dhclient is running and dhcp not set, stop dhclient
            for interface in stop_dhclient_interfaces:
                logger.debug('Calling stop_dhclient_interfaces() for %s' %
                             interface)
                if not self.noop:
                    stop_dhclient_process(interface)

            for interface in restart_interfaces:
                if not self.noop:
                    self.ifup(interface)

            for bond in self.bond_primary_ifaces:
                logger.debug('Setting active slave for %s' % bond)
                if not self.noop:
                    self.ovs_appctl('bond/set-active-slave', bond,
                                    self.bond_primary_ifaces[bond])

            # for interface in self.ovs_commands:
            #     for command in self.ovs_commands[interface]:
            #         msg = "Running ovs-vsctl %s" % command
            #         logger.debug(msg)
            #         if not self.noop:
            #             self.execute(msg, utils.ovs_vsctl_path(), cmd)

            if self.errors:
                message = 'Failure(s) occurred when applying configuration'
                logger.error(message)
                for e in self.errors:
                    logger.error(str(e))
                raise os_net_config.ConfigurationError(message)

        return update_files

