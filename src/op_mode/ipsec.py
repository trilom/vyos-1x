#!/usr/bin/env python3
#
# Copyright (C) 2022-2023 VyOS maintainers and contributors
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 or later as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
import sys
import typing

from hurry import filesize
from re import split as re_split
from tabulate import tabulate

from vyos.util import convert_data
from vyos.util import seconds_to_human
from vyos.configquery import ConfigTreeQuery

import vyos.opmode
import vyos.ipsec


def _convert(text):
    return int(text) if text.isdigit() else text.lower()


def _alphanum_key(key):
    return [_convert(c) for c in re_split('([0-9]+)', str(key))]


def _get_raw_data_sas():
    try:
        get_sas = vyos.ipsec.get_vici_sas()
        sas = convert_data(get_sas)
        return sas
    except (vyos.ipsec.ViciInitiateError) as err:
        raise vyos.opmode.UnconfiguredSubsystem(err)

def _get_formatted_output_sas(sas):
    sa_data = []
    for sa in sas:
        for parent_sa in sa.values():
            # create an item for each child-sa
            for child_sa in parent_sa.get('child-sas', {}).values():
                # prepare a list for output data
                sa_out_name = sa_out_state = sa_out_uptime = sa_out_bytes = sa_out_packets = sa_out_remote_addr = sa_out_remote_id = sa_out_proposal = 'N/A'

                # collect raw data
                sa_name = child_sa.get('name')
                sa_state = child_sa.get('state')
                sa_uptime = child_sa.get('install-time')
                sa_bytes_in = child_sa.get('bytes-in')
                sa_bytes_out = child_sa.get('bytes-out')
                sa_packets_in = child_sa.get('packets-in')
                sa_packets_out = child_sa.get('packets-out')
                sa_remote_addr = parent_sa.get('remote-host')
                sa_remote_id = parent_sa.get('remote-id')
                sa_proposal_encr_alg = child_sa.get('encr-alg')
                sa_proposal_integ_alg = child_sa.get('integ-alg')
                sa_proposal_encr_keysize = child_sa.get('encr-keysize')
                sa_proposal_dh_group = child_sa.get('dh-group')

                # format data to display
                if sa_name:
                    sa_out_name = sa_name
                if sa_state:
                    if sa_state == 'INSTALLED':
                        sa_out_state = 'up'
                    else:
                        sa_out_state = 'down'
                if sa_uptime:
                    sa_out_uptime = seconds_to_human(sa_uptime)
                if sa_bytes_in and sa_bytes_out:
                    bytes_in = filesize.size(int(sa_bytes_in))
                    bytes_out = filesize.size(int(sa_bytes_out))
                    sa_out_bytes = f'{bytes_in}/{bytes_out}'
                if sa_packets_in and sa_packets_out:
                    packets_in = filesize.size(int(sa_packets_in),
                                               system=filesize.si)
                    packets_out = filesize.size(int(sa_packets_out),
                                                system=filesize.si)
                    packets_str = f'{packets_in}/{packets_out}'
                    sa_out_packets = re.sub(r'B', r'', packets_str)
                if sa_remote_addr:
                    sa_out_remote_addr = sa_remote_addr
                if sa_remote_id:
                    sa_out_remote_id = sa_remote_id
                # format proposal
                if sa_proposal_encr_alg:
                    sa_out_proposal = sa_proposal_encr_alg
                if sa_proposal_encr_keysize:
                    sa_proposal_encr_keysize_str = sa_proposal_encr_keysize
                    sa_out_proposal = f'{sa_out_proposal}_{sa_proposal_encr_keysize_str}'
                if sa_proposal_integ_alg:
                    sa_proposal_integ_alg_str = sa_proposal_integ_alg
                    sa_out_proposal = f'{sa_out_proposal}/{sa_proposal_integ_alg_str}'
                if sa_proposal_dh_group:
                    sa_proposal_dh_group_str = sa_proposal_dh_group
                    sa_out_proposal = f'{sa_out_proposal}/{sa_proposal_dh_group_str}'

                # add a new item to output data
                sa_data.append([
                    sa_out_name, sa_out_state, sa_out_uptime, sa_out_bytes,
                    sa_out_packets, sa_out_remote_addr, sa_out_remote_id,
                    sa_out_proposal
                ])

    headers = [
        "Connection", "State", "Uptime", "Bytes In/Out", "Packets In/Out",
        "Remote address", "Remote ID", "Proposal"
    ]
    sa_data = sorted(sa_data, key=_alphanum_key)
    output = tabulate(sa_data, headers)
    return output


# Connections block

def _get_convert_data_connections():
    try:
        get_connections = vyos.ipsec.get_vici_connections()
        connections = convert_data(get_connections)
        return connections
    except (vyos.ipsec.ViciInitiateError) as err:
        raise vyos.opmode.UnconfiguredSubsystem(err)

def _get_parent_sa_proposal(connection_name: str, data: list) -> dict:
    """Get parent SA proposals by connection name
    if connections not in the 'down' state

    Args:
        connection_name (str): Connection name
        data (list): List of current SAs from vici

    Returns:
        str: Parent SA connection proposal
             AES_CBC/256/HMAC_SHA2_256_128/MODP_1024
    """
    if not data:
        return {}
    for sa in data:
        # check if parent SA exist
        if connection_name not in sa.keys():
            continue
        if 'encr-alg' in sa[connection_name]:
            encr_alg = sa.get(connection_name, '').get('encr-alg')
            cipher = encr_alg.split('_')[0]
            mode = encr_alg.split('_')[1]
            encr_keysize = sa.get(connection_name, '').get('encr-keysize')
            integ_alg = sa.get(connection_name, '').get('integ-alg')
            # prf_alg = sa.get(connection_name, '').get('prf-alg')
            dh_group = sa.get(connection_name, '').get('dh-group')
            proposal = {
                'cipher': cipher,
                'mode': mode,
                'key_size': encr_keysize,
                'hash': integ_alg,
                'dh': dh_group
            }
            return proposal
        return {}


def _get_parent_sa_state(connection_name: str, data: list) -> str:
    """Get parent SA state by connection name

    Args:
        connection_name (str): Connection name
        data (list): List of current SAs from vici

    Returns:
        Parent SA connection state
    """
    ike_state = 'down'
    if not data:
        return ike_state
    for sa in data:
        # check if parent SA exist
        for connection, connection_conf in sa.items():
            if connection_name != connection:
                continue
            if connection_conf['state'].lower() == 'established':
                ike_state = 'up'
    return ike_state


def _get_child_sa_state(connection_name: str, tunnel_name: str,
                        data: list) -> str:
    """Get child SA state by connection and tunnel name

    Args:
        connection_name (str): Connection name
        tunnel_name (str): Tunnel name
        data (list): List of current SAs from vici

    Returns:
        str: `up` if child SA state is 'installed' otherwise `down`
    """
    child_sa = 'down'
    if not data:
        return child_sa
    for sa in data:
        # check if parent SA exist
        if connection_name not in sa.keys():
            continue
        child_sas = sa[connection_name]['child-sas']
        # Get all child SA states
        # there can be multiple SAs per tunnel
        child_sa_states = [
            v['state'] for k, v in child_sas.items() if
            v['name'] == tunnel_name
        ]
        return 'up' if 'INSTALLED' in child_sa_states else child_sa


def _get_child_sa_info(connection_name: str, tunnel_name: str,
                       data: list) -> dict:
    """Get child SA installed info by connection and tunnel name

    Args:
        connection_name (str): Connection name
        tunnel_name (str): Tunnel name
        data (list): List of current SAs from vici

    Returns:
        dict: Info of the child SA in the dictionary format
    """
    for sa in data:
        # check if parent SA exist
        if connection_name not in sa.keys():
            continue
        child_sas = sa[connection_name]['child-sas']
        # Get all child SA data
        # Skip temp SA name (first key), get only SA values as dict
        # {'OFFICE-B-tunnel-0-46': {'name': 'OFFICE-B-tunnel-0'}...}
        # i.e get all data after 'OFFICE-B-tunnel-0-46'
        child_sa_info = [
            v for k, v in child_sas.items() if 'name' in v and
            v['name'] == tunnel_name and v['state'] == 'INSTALLED'
        ]
        return child_sa_info[-1] if child_sa_info else {}


def _get_child_sa_proposal(child_sa_data: dict) -> dict:
    if child_sa_data and 'encr-alg' in child_sa_data:
        encr_alg = child_sa_data.get('encr-alg')
        cipher = encr_alg.split('_')[0]
        mode = encr_alg.split('_')[1]
        key_size = child_sa_data.get('encr-keysize')
        integ_alg = child_sa_data.get('integ-alg')
        dh_group = child_sa_data.get('dh-group')
        proposal = {
            'cipher': cipher,
            'mode': mode,
            'key_size': key_size,
            'hash': integ_alg,
            'dh': dh_group
        }
        return proposal
    return {}


def _get_raw_data_connections(list_connections: list, list_sas: list) -> list:
    """Get configured VPN IKE connections and IPsec states

    Args:
        list_connections (list): List of configured connections from vici
        list_sas (list): List of current SAs from vici

    Returns:
        list: List and status of IKE/IPsec connections/tunnels
    """
    base_dict = []
    for connections in list_connections:
        base_list = {}
        for connection, conn_conf in connections.items():
            base_list['ike_connection_name'] = connection
            base_list['ike_connection_state'] = _get_parent_sa_state(
                connection, list_sas)
            base_list['ike_remote_address'] = conn_conf['remote_addrs']
            base_list['ike_proposal'] = _get_parent_sa_proposal(
                connection, list_sas)
            base_list['local_id'] = conn_conf.get('local-1', '').get('id')
            base_list['remote_id'] = conn_conf.get('remote-1', '').get('id')
            base_list['version'] = conn_conf.get('version', 'IKE')
            base_list['children'] = []
            children = conn_conf['children']
            for tunnel, tun_options in children.items():
                state = _get_child_sa_state(connection, tunnel, list_sas)
                local_ts = tun_options.get('local-ts')
                remote_ts = tun_options.get('remote-ts')
                dpd_action = tun_options.get('dpd_action')
                close_action = tun_options.get('close_action')
                sa_info = _get_child_sa_info(connection, tunnel, list_sas)
                esp_proposal = _get_child_sa_proposal(sa_info)
                base_list['children'].append({
                    'name': tunnel,
                    'state': state,
                    'local_ts': local_ts,
                    'remote_ts': remote_ts,
                    'dpd_action': dpd_action,
                    'close_action': close_action,
                    'sa': sa_info,
                    'esp_proposal': esp_proposal
                })
        base_dict.append(base_list)
    return base_dict


def _get_raw_connections_summary(list_conn, list_sas):
    import jmespath
    data = _get_raw_data_connections(list_conn, list_sas)
    match = '[*].children[]'
    child = jmespath.search(match, data)
    tunnels_down = len([k for k in child if k['state'] == 'down'])
    tunnels_up = len([k for k in child if k['state'] == 'up'])
    tun_dict = {
        'tunnels': child,
        'total': len(child),
        'down': tunnels_down,
        'up': tunnels_up
    }
    return tun_dict


def _get_formatted_output_conections(data):
    from tabulate import tabulate
    data_entries = ''
    connections = []
    for entry in data:
        tunnels = []
        ike_name = entry['ike_connection_name']
        ike_state = entry['ike_connection_state']
        conn_type = entry.get('version', 'IKE')
        remote_addrs = ','.join(entry['ike_remote_address'])
        local_ts, remote_ts = '-', '-'
        local_id = entry['local_id']
        remote_id = entry['remote_id']
        proposal = '-'
        if entry.get('ike_proposal'):
            proposal = (f'{entry["ike_proposal"]["cipher"]}_'
                        f'{entry["ike_proposal"]["mode"]}/'
                        f'{entry["ike_proposal"]["key_size"]}/'
                        f'{entry["ike_proposal"]["hash"]}/'
                        f'{entry["ike_proposal"]["dh"]}')
        connections.append([
            ike_name, ike_state, conn_type, remote_addrs, local_ts, remote_ts,
            local_id, remote_id, proposal
        ])
        for tun in entry['children']:
            tun_name = tun.get('name')
            tun_state = tun.get('state')
            conn_type = 'IPsec'
            local_ts = '\n'.join(tun.get('local_ts'))
            remote_ts = '\n'.join(tun.get('remote_ts'))
            proposal = '-'
            if tun.get('esp_proposal'):
                proposal = (f'{tun["esp_proposal"]["cipher"]}_'
                            f'{tun["esp_proposal"]["mode"]}/'
                            f'{tun["esp_proposal"]["key_size"]}/'
                            f'{tun["esp_proposal"]["hash"]}/'
                            f'{tun["esp_proposal"]["dh"]}')
            connections.append([
                tun_name, tun_state, conn_type, remote_addrs, local_ts,
                remote_ts, local_id, remote_id, proposal
            ])
    connection_headers = [
        'Connection', 'State', 'Type', 'Remote address', 'Local TS',
        'Remote TS', 'Local id', 'Remote id', 'Proposal'
    ]
    output = tabulate(connections, connection_headers, numalign='left')
    return output


# Connections block end


def _get_childsa_id_list(ike_sas: list) -> list:
    """
    Generate list of CHILD SA ids based on list of OrderingDict
    wich is returned by vici
    :param ike_sas: list of IKE SAs generated by vici
    :type ike_sas: list
    :return: list of IKE SAs ids
    :rtype: list
    """
    list_childsa_id: list = []
    for ike in ike_sas:
        for ike_sa in ike.values():
            for child_sa in ike_sa['child-sas'].values():
                list_childsa_id.append(child_sa['uniqueid'].decode('ascii'))
    return list_childsa_id


def _get_all_sitetosite_peers_name_list() -> list:
    """
    Return site-to-site peers configuration
    :return: site-to-site peers configuration
    :rtype: list
    """
    conf: ConfigTreeQuery = ConfigTreeQuery()
    config_path = ['vpn', 'ipsec', 'site-to-site', 'peer']
    peers_config = conf.get_config_dict(config_path, key_mangling=('-', '_'),
                                       get_first_key=True,
                                       no_tag_node_value_mangle=True)
    peers_list: list = []
    for name in peers_config:
        peers_list.append(name)
    return peers_list


def reset_peer(peer: str, tunnel: typing.Optional[str] = None):
    # Convert tunnel to Strongwan format of CHILD_SA
    tunnel_sw = None
    if tunnel:
        if tunnel.isnumeric():
            tunnel_sw = f'{peer}-tunnel-{tunnel}'
        elif tunnel == 'vti':
            tunnel_sw = f'{peer}-vti'
    try:
        sa_list: list = vyos.ipsec.get_vici_sas_by_name(peer, tunnel_sw)
        if not sa_list:
            raise vyos.opmode.IncorrectValue(
                f'Peer\'s {peer} SA(s) not found, aborting')
        if tunnel and sa_list:
            childsa_id_list: list = _get_childsa_id_list(sa_list)
            if not childsa_id_list:
                raise vyos.opmode.IncorrectValue(
                    f'Peer {peer} tunnel {tunnel} SA(s) not found, aborting')
        vyos.ipsec.terminate_vici_by_name(peer, tunnel_sw)
        print(f'Peer {peer} reset result: success')
    except (vyos.ipsec.ViciInitiateError) as err:
        raise vyos.opmode.UnconfiguredSubsystem(err)
    except (vyos.ipsec.ViciCommandError) as err:
        raise vyos.opmode.IncorrectValue(err)

def reset_all_peers():
    sitetosite_list = _get_all_sitetosite_peers_name_list()
    if sitetosite_list:
        for peer_name in sitetosite_list:
            try:
                reset_peer(peer_name)
            except (vyos.opmode.IncorrectValue) as err:
                print(err)
        print('Peers reset result: success')
    else:
        raise vyos.opmode.UnconfiguredSubsystem(
            'VPN IPSec site-to-site is not configured, aborting')

def _get_ra_session_list_by_username(username: typing.Optional[str] = None):
    """
    Return list of remote-access IKE_SAs uniqueids
    :param username:
    :type username:
    :return:
    :rtype:
    """
    list_sa_id = []
    sa_list = vyos.ipsec.get_vici_sas()
    for sa_val in sa_list:
        for sa in sa_val.values():
            if 'remote-eap-id' in sa:
                if username:
                    if username == sa['remote-eap-id'].decode():
                        list_sa_id.append(sa['uniqueid'].decode())
                else:
                    list_sa_id.append(sa['uniqueid'].decode())
    return list_sa_id


def reset_ra(username: typing.Optional[str] = None):
    #Reset remote-access ipsec sessions
    if username:
        list_sa_id = _get_ra_session_list_by_username(username)
    else:
        list_sa_id = _get_ra_session_list_by_username()
    if list_sa_id:
        vyos.ipsec.terminate_vici_ikeid_list(list_sa_id)


def reset_profile_dst(profile: str, tunnel: str, nbma_dst: str):
    if profile and tunnel and nbma_dst:
        ike_sa_name = f'dmvpn-{profile}-{tunnel}'
        try:
            # Get IKE SAs
            sa_list = convert_data(
                vyos.ipsec.get_vici_sas_by_name(ike_sa_name, None))
            if not sa_list:
                raise vyos.opmode.IncorrectValue(
                    f'SA(s) for profile {profile} tunnel {tunnel} not found, aborting')
            sa_nbma_list = list([x for x in sa_list if
                                 ike_sa_name in x and x[ike_sa_name][
                                     'remote-host'] == nbma_dst])
            if not sa_nbma_list:
                raise vyos.opmode.IncorrectValue(
                    f'SA(s) for profile {profile} tunnel {tunnel} remote-host {nbma_dst} not found, aborting')
            # terminate IKE SAs
            vyos.ipsec.terminate_vici_ikeid_list(list(
                [x[ike_sa_name]['uniqueid'] for x in sa_nbma_list if
                 ike_sa_name in x]))
            # initiate IKE SAs
            for ike in sa_nbma_list:
                if ike_sa_name in ike:
                    vyos.ipsec.vici_initiate(ike_sa_name, 'dmvpn',
                                             ike[ike_sa_name]['local-host'],
                                             ike[ike_sa_name]['remote-host'])
            print(
                f'Profile {profile} tunnel {tunnel} remote-host {nbma_dst} reset result: success')
        except (vyos.ipsec.ViciInitiateError) as err:
            raise vyos.opmode.UnconfiguredSubsystem(err)
        except (vyos.ipsec.ViciCommandError) as err:
            raise vyos.opmode.IncorrectValue(err)


def reset_profile_all(profile: str, tunnel: str):
    if profile and tunnel:
        ike_sa_name = f'dmvpn-{profile}-{tunnel}'
        try:
            # Get IKE SAs
            sa_list: list = convert_data(
                vyos.ipsec.get_vici_sas_by_name(ike_sa_name, None))
            if not sa_list:
                raise vyos.opmode.IncorrectValue(
                    f'SA(s) for profile {profile} tunnel {tunnel} not found, aborting')
            # terminate IKE SAs
            vyos.ipsec.terminate_vici_by_name(ike_sa_name, None)
            # initiate IKE SAs
            for ike in sa_list:
                if ike_sa_name in ike:
                    vyos.ipsec.vici_initiate(ike_sa_name, 'dmvpn',
                                             ike[ike_sa_name]['local-host'],
                                             ike[ike_sa_name]['remote-host'])
                print(
                    f'Profile {profile} tunnel {tunnel} remote-host {ike[ike_sa_name]["remote-host"]} reset result: success')
            print(f'Profile {profile} tunnel {tunnel} reset result: success')
        except (vyos.ipsec.ViciInitiateError) as err:
            raise vyos.opmode.UnconfiguredSubsystem(err)
        except (vyos.ipsec.ViciCommandError) as err:
            raise vyos.opmode.IncorrectValue(err)


def show_sa(raw: bool):
    sa_data = _get_raw_data_sas()
    if raw:
        return sa_data
    return _get_formatted_output_sas(sa_data)


def show_connections(raw: bool):
    list_conns = _get_convert_data_connections()
    list_sas = _get_raw_data_sas()
    if raw:
        return _get_raw_data_connections(list_conns, list_sas)

    connections = _get_raw_data_connections(list_conns, list_sas)
    return _get_formatted_output_conections(connections)


def show_connections_summary(raw: bool):
    list_conns = _get_convert_data_connections()
    list_sas = _get_raw_data_sas()
    if raw:
        return _get_raw_connections_summary(list_conns, list_sas)


if __name__ == '__main__':
    try:
        res = vyos.opmode.run(sys.modules[__name__])
        if res:
            print(res)
    except (ValueError, vyos.opmode.Error) as e:
        print(e)
        sys.exit(1)
