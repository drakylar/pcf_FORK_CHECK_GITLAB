from routes.ui import routes
from app import check_session, db, redirect, render_template, request, \
    send_log_data, requires_authorization, csrf
from .project import check_project_access, check_project_archived
from system.forms import *
from libnmap.parser import NmapParser
from libnessus.parser import NessusParser
import json
import codecs
import re
import io
from flask import Response, send_file
from bs4 import BeautifulSoup
import urllib.parse
from IPy import IP
import socket
import csv
import dicttoxml
import time
from xml.dom.minidom import parseString
import ipwhois
import shodan
import ipaddress
import whois

from routes.ui.tools_addons import nmap_scripts


@routes.route('/project/<uuid:project_id>/tools/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_tools(project_id, current_project, current_user):
    return render_template('project/tools/list.html',
                           current_project=current_project,
                           tab_name='Tools')


@routes.route('/project/<uuid:project_id>/tools/nmap/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def nmap_page(project_id, current_project, current_user):
    return render_template('project/tools/import/nmap.html',
                           current_project=current_project,
                           tab_name='Nmap')


@routes.route('/project/<uuid:project_id>/tools/nmap/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def nmap_page_form(project_id, current_project, current_user):
    form = NmapForm()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        add_empty_hosts = form.add_no_open.data

        # parse ports
        ignore_ports = form.ignore_ports.data.replace(' ', '')
        ignore_port_arr1 = ignore_ports.split(',') if ignore_ports else []
        ignore_port_array = []
        for port_str in ignore_port_arr1:
            protocol = 'tcp'
            port_num = port_str
            if '/' in port_str:
                if port_str.split('/')[1].lower() == 'udp':
                    protocol = 'udp'
                port_num = port_str.split('/')[0]
            port_num = int(port_num)
            ignore_port_array.append([port_num, protocol])

        ignore_services_array = [service.lower() for service in form.ignore_services.data.replace(' ', '').split(',')]

        for file in form.files.data:
            try:
                xml_report_data = file.read().decode('charmap')
                nmap_report = NmapParser.parse_fromstring(xml_report_data)
            except:
                return render_template('project/tools/import/nmap.html',
                                       current_project=current_project,
                                       errors=['Оne of uploaded files was incorrect!'],
                                       success=1,
                                       tab_name='Nmap')
            try:
                command_str = nmap_report.commandline
            except:
                command_str = ''
            for host in nmap_report.hosts:
                # check if we will add host
                found = 0
                os = ''
                if host.os and host.os.osmatches:
                    os = host.os.osmatches[0].name
                for service in host.services:
                    protocol = service.protocol.lower()
                    port_num = int(service.port)
                    service_name = service.service.lower()
                    if [port_num, protocol] not in ignore_port_array and service_name not in ignore_services_array:
                        if service.state == 'open':
                            found = 1
                        elif service.state == 'filtered' and \
                                form.rule.data in ['filtered', 'closed']:
                            found = 1
                        elif service.state == 'closed' and \
                                form.rule.data == 'closed':
                            found = 1
                if found or add_empty_hosts:
                    host_id = db.select_project_host_by_ip(
                        current_project['id'], host.address)
                    if not host_id:
                        host_info = 'Added from NMAP scan'
                        host_id = db.insert_host(current_project['id'],
                                                 host.address,
                                                 current_user['id'],
                                                 host_info)
                    else:
                        host_id = host_id[0]['id']
                    if os:
                        db.update_host_os(host_id, os)
                    for hostname in host.hostnames:
                        if hostname and hostname != host.address:
                            hostname_id = db.select_ip_hostname(host_id,
                                                                hostname)
                            if not hostname_id:
                                hostname_id = db.insert_hostname(host_id,
                                                                 hostname,
                                                                 'Added from NMAP scan',
                                                                 current_user[
                                                                     'id'])
                            else:
                                hostname_id = hostname_id[0]['id']
                    for service in host.services:
                        is_tcp = service.protocol == 'tcp'
                        protocol_str = service.protocol.lower()
                        port_num = int(service.port)
                        service_name = service.service
                        service_banner = service.banner
                        add = 0
                        if [port_num,
                            protocol_str] not in ignore_port_array and service_name.lower() not in ignore_services_array:
                            if service.state == 'open':
                                add = 1
                            elif service.state == 'filtered' and \
                                    form.rule.data in ['filtered', 'closed']:
                                add = 1
                                service_banner += '\nstate: filtered'
                            elif service.state == 'closed' and \
                                    form.rule.data == 'closed':
                                add = 1
                                service_banner += '\nstate: closed'
                        if add == 1:
                            port_id = db.select_ip_port(host_id, service.port,
                                                        is_tcp)
                            if not port_id:
                                port_id = db.insert_host_port(host_id,
                                                              service.port,
                                                              is_tcp,
                                                              service_name,
                                                              service_banner,
                                                              current_user[
                                                                  'id'],
                                                              current_project[
                                                                  'id'])
                            else:
                                port_id = port_id[0]['id']
                                db.update_port_proto_description(port_id,
                                                                 service_name,
                                                                 service_banner)

                            for script_xml in service.scripts_results:
                                for script in nmap_scripts.modules:
                                    script_class = script.nmap_plugin
                                    if script_class.script_id == script_xml['id'] and \
                                            script_class.script_source == 'service':
                                        script_obj = script_class(script_xml)

                                        if 'port_info' in script_obj.script_types:
                                            result = script_obj.port_info()
                                            update = False
                                            if 'protocol' in result and result['protocol'] and \
                                                    result['protocol'].lower() not in service_name.lower():
                                                service_name = result['protocol']
                                                update = True
                                            if 'info' in result and result['info'] and \
                                                    result['info'].lower() not in service_banner.lower():
                                                service_banner += '\n' + result['info']
                                                update = True
                                            if update:
                                                db.update_port_proto_description(port_id,
                                                                                 service_name,
                                                                                 service_banner)

                                        if 'issue' in script_obj.script_types:
                                            issues = script_obj.issues()
                                            for issue in issues:
                                                db.insert_new_issue_no_dublicate(issue['name'],
                                                                                 issue[
                                                                                     'description'] if 'description' in issue else '',
                                                                                 issue['path'] if 'path' in issue else '',
                                                                                 issue['cvss'] if 'cvss' in issue else 0.0,
                                                                                 current_user['id'],
                                                                                 {port_id: ['0']},
                                                                                 'need to recheck',
                                                                                 current_project['id'],
                                                                                 cve=issue['cve'] if 'cve' in issue else '',
                                                                                 cwe=issue['cwe'] if 'cwe' in issue else 0,
                                                                                 issue_type='service',
                                                                                 fix=issue['fix'] if 'fix' in issue else '',
                                                                                 param=issue[
                                                                                     'params'] if 'params' in issue else '')

                                        if 'credentials' in script_obj.script_types:
                                            credentials = script_obj.credentials()
                                            for cred in credentials:
                                                login = cred['login'] if 'login' in cred else ''
                                                cleartext = cred['cleartext'] if 'cleartext' in cred else ''
                                                hash_str = cred['hash'] if 'hash' in cred else ''
                                                description = cred['description'] if 'description' in cred else ''
                                                source = cred['source'] if 'source' in cred else ''

                                                dublicates_creds = db.select_creds_dublicates(current_project['id'],
                                                                                              login,
                                                                                              hash_str, cleartext,
                                                                                              description,
                                                                                              source)

                                                if dublicates_creds:
                                                    dublicates_creds = dublicates_creds[0]
                                                    services = json.loads(dublicates_creds['services'])
                                                    if port_id not in services:
                                                        services[port_id] = ["0"]
                                                    else:
                                                        services[port_id].append("0")

                                                    db.update_creds(dublicates_creds['id'],
                                                                    login,
                                                                    hash_str,
                                                                    dublicates_creds['hash_type'],
                                                                    cleartext,
                                                                    description,
                                                                    source,
                                                                    services)
                                                else:
                                                    db.insert_new_cred(login,
                                                                       hash_str,
                                                                       'other',
                                                                       cleartext,
                                                                       description,
                                                                       source,
                                                                       {port_id: ["0"]},
                                                                       current_user['id'],
                                                                       current_project['id'])

                    current_host = db.select_host(host_id)[0]
                    host_zero_port = db.select_host_port(current_host['id'])[0]
                    for script_xml in host.scripts_results:
                        for script in nmap_scripts.modules:
                            script_class = script.nmap_plugin
                            if script_class.script_id == script_xml['id'] and \
                                    script_class.script_source == 'host':
                                script_obj = script_class(script_xml)

                                if 'server_info' in script_obj.script_types:
                                    result = script_obj.host_info()
                                    update = False
                                    if 'os' in result and result['os'] and \
                                            result['os'].lower() not in current_host['os'].lower():
                                        current_host['os'] = result['os']
                                        update = True
                                    if 'info' in result and result['info'] and \
                                            result['info'].lower() not in current_host['comment'].lower():
                                        current_host['comment'] += '\n' + result['info']
                                        update = True
                                    if update:
                                        db.update_host_comment_threats(current_host['id'],
                                                                       current_host['comment'],
                                                                       current_host['threats'],
                                                                       current_host['os'])
                                    if 'hostnames' in result:
                                        for hostname in result['hostnames']:
                                            hostnames_found = db.select_ip_hostname(current_host['id'], hostname)
                                            if not hostnames_found:
                                                db.insert_hostname(current_host['id'], hostname,
                                                                   'From nmap scan', current_user['id'])

                                if 'issue' in script_obj.script_types:
                                    issues = script_obj.issues()
                                    for issue in issues:
                                        db.insert_new_issue_no_dublicate(issue['name'],
                                                                         issue[
                                                                             'description'] if 'description' in issue else '',
                                                                         issue['path'] if 'path' in issue else '',
                                                                         issue['cvss'] if 'cvss' in issue else 0.0,
                                                                         current_user['id'],
                                                                         {host_zero_port['id']: ['0']},
                                                                         'need to recheck',
                                                                         current_project['id'],
                                                                         cve=issue['cve'] if 'cve' in issue else '',
                                                                         cwe=issue['cwe'] if 'cwe' in issue else 0,
                                                                         issue_type='service',
                                                                         fix=issue['fix'] if 'fix' in issue else '',
                                                                         param=issue[
                                                                             'params'] if 'params' in issue else '')

                                if 'credentials' in script_obj.script_types:
                                    credentials = script_obj.credentials()
                                    for cred in credentials:
                                        login = cred['login'] if 'login' in cred else ''
                                        cleartext = cred['cleartext'] if 'cleartext' in cred else ''
                                        hash_str = cred['hash'] if 'hash' in cred else ''
                                        description = cred['description'] if 'description' in cred else ''
                                        source = cred['source'] if 'source' in cred else ''

                                        dublicates_creds = db.select_creds_dublicates(current_project['id'],
                                                                                      login,
                                                                                      hash_str, cleartext,
                                                                                      description,
                                                                                      source)

                                        if dublicates_creds:
                                            dublicates_creds = dublicates_creds[0]
                                            services = json.loads(dublicates_creds['services'])
                                            if host_zero_port['id'] not in services:
                                                services[host_zero_port['id']] = ["0"]
                                            else:
                                                services[host_zero_port['id']].append("0")

                                            db.update_creds(dublicates_creds['id'],
                                                            login,
                                                            hash_str,
                                                            dublicates_creds['hash_type'],
                                                            cleartext,
                                                            description,
                                                            source,
                                                            services)
                                        else:
                                            db.insert_new_cred(login,
                                                               hash_str,
                                                               'other',
                                                               cleartext,
                                                               description,
                                                               source,
                                                               {host_zero_port['id']: ["0"]},
                                                               current_user['id'],
                                                               current_project['id'])

    return render_template('project/tools/import/nmap.html',
                           current_project=current_project,
                           errors=errors,
                           success=1,
                           tab_name='Nmap')


@routes.route('/project/<uuid:project_id>/tools/nessus/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def nessus_page(project_id, current_project, current_user):
    return render_template('project/tools/import/nessus.html',
                           current_project=current_project,
                           tab_name='Nessus')


@routes.route('/project/<uuid:project_id>/tools/nessus/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def nessus_page_form(project_id, current_project, current_user):
    form = NessusForm()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        add_info_issues = form.add_info_issues.data
        # xml files
        for file in form.xml_files.data:
            if file.filename:
                xml_report_data = file.read().decode('charmap')
                scan_result = NessusParser.parse_fromstring(xml_report_data)
                for host in scan_result.hosts:
                    host_id = db.select_project_host_by_ip(
                        current_project['id'], host.ip)
                    if not host_id:
                        host_id = db.insert_host(current_project['id'],
                                                 host.ip,
                                                 current_user['id'],
                                                 'Added from Nessus scan')
                    else:
                        host_id = host_id[0]['id']

                    # add hostname
                    hostname_id = ''
                    hostname = host.name if host.name != host.ip else ''
                    try:
                        test_hostname = IP(host.address)
                    except ValueError:
                        test_hostname = ''
                    if not hostname and not test_hostname and host.address:
                        hostname = host.address
                    if hostname:
                        hostname_id = db.select_ip_hostname(host_id, hostname)
                        if not hostname_id:
                            hostname_id = db.insert_hostname(host_id,
                                                             hostname,
                                                             'Added from Nessus scan',
                                                             current_user['id'])
                        else:
                            hostname_id = hostname_id[0]['id']

                    for issue in host.get_report_items:

                        # create port

                        is_tcp = issue.protocol == 'tcp'
                        port_id = db.select_ip_port(host_id, int(issue.port),
                                                    is_tcp)
                        if not port_id:
                            port_id = db.insert_host_port(host_id,
                                                          issue.port,
                                                          is_tcp,
                                                          issue.service,
                                                          'Added from Nessus scan',
                                                          current_user['id'],
                                                          current_project['id'])
                        else:
                            port_id = port_id[0]['id']
                            db.update_port_service(port_id,
                                                   issue.service)
                        # add issue to created port

                        name = 'Nessus: {}'.format(issue.plugin_name)
                        try:
                            issue_info = issue.synopsis
                        except KeyError:
                            issue_info = ''

                        description = 'Plugin name: {}\r\n\r\nInfo: \r\n{} \r\n\r\nOutput: \r\n {}'.format(
                            issue.plugin_name,
                            issue_info,
                            issue.description.strip('\n'))
                        # add host OS
                        if issue.get_vuln_plugin["pluginName"] == 'OS Identification':
                            os = issue.get_vuln_plugin["plugin_output"].split('\n')[1].split(' : ')[1]
                            db.update_host_os(host_id, os)
                        cve = issue.cve.replace('[', '').replace(']', '').replace("'", '').replace(",", ', ') if issue.cve else ''
                        cvss = 0
                        severity = float(issue.severity)
                        if severity == 0 and issue.get_vuln_info['risk_factor'] == 'None':
                            cvss = 0
                        elif 'cvss3_base_score' in issue.get_vuln_info:
                            cvss = float(issue.get_vuln_info['cvss3_base_score'])
                        elif 'cvss_base_score' in issue.get_vuln_info:
                            cvss = float(issue.get_vuln_info['cvss_base_score'])
                        else:
                            pass
                        if hostname_id:
                            services = {port_id: ['0', hostname_id]}
                        else:
                            services = {port_id: ['0']}
                        if severity > 0 or (severity == 0 and add_info_issues):
                            db.insert_new_issue_no_dublicate(name, description, '', cvss,
                                                             current_user['id'], services,
                                                             'need to check',
                                                             current_project['id'],
                                                             cve, cwe=0, issue_type='custom', fix=issue.solution)

    return render_template('project/tools/import/nessus.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='Nessus')


@routes.route('/project/<uuid:project_id>/tools/nikto/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def nikto_page(project_id, current_project, current_user):
    return render_template('project/tools/import/nikto.html',
                           current_project=current_project,
                           tab_name='Nikto')


@routes.route('/project/<uuid:project_id>/tools/nikto/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def nikto_page_form(project_id, current_project, current_user):
    form = NiktoForm()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        # json files
        for file in form.json_files.data:
            if file.filename:
                json_report_data = file.read().decode('charmap').replace(',]',
                                                                         ']').replace(
                    ',}', '}')
                scan_result = json.loads(json_report_data)
                host = scan_result['ip']
                hostname = scan_result['host'] if scan_result['ip'] != \
                                                  scan_result['host'] else ''
                issues = scan_result['vulnerabilities']
                port = int(scan_result['port'])
                protocol = 'https' if '443' in str(port) else 'http'
                is_tcp = 1
                port_description = 'Added by Nikto scan'
                if scan_result['banner']:
                    port_description = 'Nikto banner: {}'.format(
                        scan_result['banner'])

                # add host
                host_id = db.select_project_host_by_ip(current_project['id'],
                                                       host)
                if not host_id:
                    host_id = db.insert_host(current_project['id'],
                                             host,
                                             current_user['id'],
                                             'Added by Nikto scan')
                else:
                    host_id = host_id[0]['id']

                # add hostname

                hostname_id = ''
                if hostname and hostname != host:
                    hostname_id = db.select_ip_hostname(host_id, hostname)
                    if not hostname_id:
                        hostname_id = db.insert_hostname(host_id,
                                                         hostname,
                                                         'Added from Nikto scan',
                                                         current_user['id'])
                    else:
                        hostname_id = hostname_id[0]['id']

                # add port
                port_id = db.select_ip_port(host_id, port, is_tcp)
                if not port_id:
                    port_id = db.insert_host_port(host_id,
                                                  port,
                                                  is_tcp,
                                                  protocol,
                                                  port_description,
                                                  current_user['id'],
                                                  current_project['id'])
                else:
                    port_id = port_id[0]['id']

                for issue in issues:
                    method = issue['method']
                    url = issue['url']
                    full_url = '{} {}'.format(method, url)
                    osvdb = int(issue['OSVDB'])
                    info = issue['msg']
                    full_info = 'OSVDB: {}\n\n{}'.format(osvdb, info)

                    services = {port_id: ['0']}
                    if hostname_id:
                        services = {port_id: ['0', hostname_id]}

                    db.insert_new_issue('Nikto scan', full_info, full_url, 0,
                                        current_user['id'], services,
                                        'need to check',
                                        current_project['id'],
                                        cve=0,
                                        cwe=0,
                                        )
        # csv load
        for file in form.csv_files.data:
            if file.filename:
                scan_result = csv.reader(codecs.iterdecode(file, 'charmap'),
                                         delimiter=',')

                for issue in scan_result:
                    if len(issue) == 7:
                        hostname = issue[0]
                        host = issue[1]
                        port = int(issue[2])
                        protocol = 'https' if '443' in str(port) else 'http'
                        is_tcp = 1
                        osvdb = issue[3]
                        full_url = '{} {}'.format(issue[4], issue[5])
                        full_info = 'OSVDB: {}\n{}'.format(osvdb, issue[6])

                        # add host
                        host_id = db.select_project_host_by_ip(
                            current_project['id'],
                            host)
                        if not host_id:
                            host_id = db.insert_host(current_project['id'],
                                                     host,
                                                     current_user['id'],
                                                     'Added by Nikto scan')
                        else:
                            host_id = host_id[0]['id']

                        # add hostname
                        hostname_id = ''
                        if hostname and hostname != host:
                            hostname_id = db.select_ip_hostname(host_id,
                                                                hostname)
                            if not hostname_id:
                                hostname_id = db.insert_hostname(host_id,
                                                                 hostname,
                                                                 'Added from Nikto scan',
                                                                 current_user[
                                                                     'id'])
                            else:
                                hostname_id = hostname_id[0]['id']

                        # add port
                        port_id = db.select_ip_port(host_id, port, is_tcp)
                        if not port_id:
                            port_id = db.insert_host_port(host_id,
                                                          port,
                                                          is_tcp,
                                                          protocol,
                                                          'Added from Nikto scan',
                                                          current_user['id'],
                                                          current_project['id'])
                        else:
                            port_id = port_id[0]['id']

                        # add issue
                        services = {port_id: ['0']}
                        if hostname_id:
                            services = {port_id: ['0', hostname_id]}

                        db.insert_new_issue('Nikto scan', full_info, full_url,
                                            0,
                                            current_user['id'], services,
                                            'need to check',
                                            current_project['id'],
                                            cve=0,
                                            cwe=0,
                                            )

        for file in form.xml_files.data:
            if file.filename:
                scan_result = BeautifulSoup(file.read(),
                                            "html.parser").niktoscan.scandetails
                host = scan_result['targetip']
                port = int(scan_result['targetport'])
                is_tcp = 1
                port_banner = scan_result['targetbanner']
                hostname = scan_result['targethostname']
                issues = scan_result.findAll("item")
                protocol = 'https' if '443' in str(port) else 'http'
                port_description = ''
                if port_banner:
                    port_description = 'Nikto banner: {}'.format(
                        scan_result['targetbanner'])

                # add host
                host_id = db.select_project_host_by_ip(
                    current_project['id'],
                    host)
                if not host_id:
                    host_id = db.insert_host(current_project['id'],
                                             host,
                                             current_user['id'],
                                             'Added by Nikto scan')
                else:
                    host_id = host_id[0]['id']

                # add hostname
                hostname_id = ''
                if hostname and hostname != host:
                    hostname_id = db.select_ip_hostname(host_id,
                                                        hostname)
                    if not hostname_id:
                        hostname_id = db.insert_hostname(host_id,
                                                         hostname,
                                                         'Added from Nikto scan',
                                                         current_user[
                                                             'id'])
                    else:
                        hostname_id = hostname_id[0]['id']

                # add port
                port_id = db.select_ip_port(host_id, port, is_tcp)
                if not port_id:
                    port_id = db.insert_host_port(host_id,
                                                  port,
                                                  is_tcp,
                                                  protocol,
                                                  port_description,
                                                  current_user['id'],
                                                  current_project['id'])
                else:
                    port_id = port_id[0]['id']

                for issue in issues:
                    method = issue['method']
                    url = issue.uri.contents[0]
                    full_url = '{} {}'.format(method, url)
                    osvdb = int(issue['osvdbid'])
                    info = issue.description.contents[0]
                    full_info = 'OSVDB: {}\n\n{}'.format(osvdb, info)

                    services = {port_id: ['0']}
                    if hostname_id:
                        services = {port_id: ['0', hostname_id]}

                    db.insert_new_issue('Nikto scan', full_info, full_url, 0,
                                        current_user['id'], services,
                                        'need to check',
                                        current_project['id'],
                                        cve=0,
                                        cwe=0,
                                        )

    return render_template('project/tools/import/nikto.html',
                           current_project=current_project,
                           tab_name='Nikto',
                           errors=errors)


@routes.route('/project/<uuid:project_id>/tools/acunetix/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def acunetix_page(project_id, current_project, current_user):
    return render_template('project/tools/import/acunetix.html',
                           current_project=current_project,
                           tab_name='Acunetix')


@routes.route('/project/<uuid:project_id>/tools/acunetix/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def acunetix_page_form(project_id, current_project, current_user):
    form = AcunetixForm()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        auto_resolve = form.auto_resolve.data == 1

        # xml files
        for file in form.files.data:
            if file.filename:
                scan_result = BeautifulSoup(file.read(),
                                            "html.parser").scangroup.scan
                start_url = scan_result.starturl.contents[0]
                parsed_url = urllib.parse.urlparse(start_url)
                protocol = parsed_url.scheme
                hostname = parsed_url.hostname
                if hostname is None:
                    hostname = parsed_url.path
                port = parsed_url.port
                os_descr = scan_result.os.contents[0]
                port_banner = scan_result.banner.contents[0]
                web_banner = scan_result.webserver.contents[0]
                port_description = 'Banner: {} Web: {}'.format(port_banner,
                                                               web_banner)
                host_description = 'OS: {}'.format(os_descr)
                is_tcp = 1
                if not port:
                    port = 80
                    if protocol == 'https':
                        port = 443
                try:
                    IP(hostname)
                    host = hostname
                    hostname = ''
                except:
                    if form.host.data:
                        IP(form.host.data)
                        host = form.host.data
                    elif form.auto_resolve.data == 1:
                        host = socket.gethostbyname(hostname)
                    else:
                        errors.append('ip not resolved!')

                if not errors:
                    # add host
                    host_id = db.select_project_host_by_ip(current_project['id'], host)
                    if not host_id:
                        host_id = db.insert_host(current_project['id'],
                                                 host,
                                                 current_user['id'],
                                                 host_description)
                    else:
                        host_id = host_id[0]['id']
                        db.update_host_description(host_id, host_description)

                    # add hostname
                    hostname_id = ''
                    if hostname and hostname != host:
                        hostname_id = db.select_ip_hostname(host_id,
                                                            hostname)
                        if not hostname_id:
                            hostname_id = db.insert_hostname(host_id,
                                                             hostname,
                                                             'Added from Acunetix scan',
                                                             current_user['id'])
                        else:
                            hostname_id = hostname_id[0]['id']

                    # add port
                    port_id = db.select_ip_port(host_id, port, is_tcp)
                    if not port_id:
                        port_id = db.insert_host_port(host_id,
                                                      port,
                                                      is_tcp,
                                                      protocol,
                                                      port_description,
                                                      current_user['id'],
                                                      current_project['id'])
                    else:
                        port_id = port_id[0]['id']
                        db.update_port_proto_description(port_id, protocol,
                                                         port_description)
                    issues = scan_result.reportitems.findAll("reportitem")

                    for issue in issues:
                        issue_name = issue.contents[1].contents[0]
                        module_name = issue.modulename.contents[0]
                        uri = issue.affects.contents[0]
                        request_params = issue.parameter.contents[0]
                        full_uri = '{} params:{}'.format(uri, request_params)
                        impact = issue.impact.contents[0]
                        issue_description = issue.description.contents[0]
                        recomendations = issue.recommendation.contents[0]
                        issue_request = issue.technicaldetails.request.contents[
                            0]
                        cwe = 0
                        if issue.cwe:
                            cwe = int(issue.cwe['id'].replace('CWE-', ''))
                        cvss = float(issue.cvss.score.contents[0])
                        # TODO: check CVE field

                        full_info = '''Module: \n{}\n\nDescription: \n{}\n\nImpact: \n{}\n\nRecomendations: \n{}\n\nRequest: \n{}'''.format(
                            module_name, issue_description, impact,
                            recomendations, issue_request)

                        services = {port_id: ['0']}
                        if hostname_id:
                            services = {port_id: ['0', hostname_id]}

                        db.insert_new_issue(issue_name,
                                            full_info, full_uri,
                                            cvss,
                                            current_user['id'], services,
                                            'need to check',
                                            current_project['id'],
                                            cve=0,
                                            cwe=cwe
                                            )
    return render_template('project/tools/import/acunetix.html',
                           current_project=current_project,
                           tab_name='Acunetix',
                           errors=errors)


@routes.route('/project/<uuid:project_id>/tools/exporter/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def exporter_page(project_id, current_project, current_user):
    return render_template(
        'project/tools/export/exporter.html',
        current_project=current_project,
        tab_name='Exporter')


@routes.route('/project/<uuid:project_id>/tools/exporter/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def exporter_page_form(project_id, current_project, current_user):
    form = ExportHosts()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        result_hosts = db.search_hostlist(project_id=current_project['id'],
                                          network=form.network.data,
                                          ip_hostname=form.ip_hostname.data,
                                          issue_name=form.issue_name.data,
                                          port=form.port.data,
                                          service=form.service.data,
                                          comment=form.comment.data,
                                          threats=form.threats.data)
    else:
        return render_template(
            'project/tools/export/exporter.html',
            current_project=current_project,
            tab_name='Exporter',
            errors=errors)

    result = ''
    separator = '\n' if form.separator.data == '[newline]' \
        else form.separator.data
    host_export = form.hosts_export.data

    ports_array = []
    if form.port.data:
        ports_array = [[int(port.split('/')[0]), port.split('/')[1] == 'tcp']
                       for port in form.port.data.split(',')]

    prefix = form.prefix.data
    postfix = form.postfix.data

    if form.filetype.data == 'txt':
        # txt worker
        response_type = 'text/plain'
        if not form.add_ports.data:
            # no ports
            ips = [host['ip'] for host in result_hosts]
            ips_hostnames = {}
            hostnames = []
            for host in result_hosts:
                host_hostname = db.select_ip_hostnames(host['id'])
                hostnames += [hostname['hostname'] for hostname in
                              host_hostname]
                ips_hostnames[host['ip']] = host_hostname
            hostnames = list(set(hostnames))
            if host_export == 'ip':
                result = separator.join([prefix + x + postfix for x in ips])
            elif host_export == 'hostname':
                result = separator.join([prefix + x + postfix for x in hostnames])
            elif host_export == 'ip&hostname':
                result = separator.join([prefix + x + postfix for x in ips + hostnames])
            elif host_export == 'ip&hostname_unique':
                host_hostnames_arr = []
                for ip in ips_hostnames:
                    if not ips_hostnames[ip]:
                        host_hostnames_arr.append(ip)
                    else:
                        host_hostnames_arr += [hostname['hostname'] for
                                               hostname in ips_hostnames[ip]]
                result = separator.join([prefix + x + postfix for x in host_hostnames_arr])
        else:
            # with ports

            # preparation: issues

            if form.issue_name.data:
                port_ids = db.search_issues_port_ids(current_project['id'],
                                                     form.issue_name.data)

            for host in result_hosts:
                ports = db.select_host_ports(host['id'])
                hostnames = db.select_ip_hostnames(host['id'])
                for port in ports:
                    if (not form.port.data) or (
                            [port['port'], port['is_tcp']] in ports_array):
                        if form.service.data in port['service']:

                            if (not form.issue_name.data) or (
                                    port['id'] in port_ids):

                                if host_export == 'ip&hostname':
                                    result += '{}{}{}:{}{}'.format(separator,
                                                                   prefix,
                                                                   host['ip'],
                                                                   port['port'],
                                                                   postfix)
                                    for hostname in hostnames:
                                        result += '{}{}{}:{}{}'.format(separator,
                                                                       prefix,
                                                                       hostname[
                                                                           'hostname'],
                                                                       port['port'],
                                                                       postfix)
                                elif host_export == 'ip':
                                    result += '{}{}{}:{}{}'.format(separator,
                                                                   prefix,
                                                                   host['ip'],
                                                                   port['port'],
                                                                   postfix)

                                elif host_export == 'hostname':
                                    for hostname in hostnames:
                                        result += '{}{}{}:{}{}'.format(separator,
                                                                       prefix,
                                                                       hostname[
                                                                           'hostname'],
                                                                       port['port'],
                                                                       postfix)

                                elif host_export == 'ip&hostname_unique':
                                    if hostnames:
                                        for hostname in hostnames:
                                            result += '{}{}{}:{}{}'.format(
                                                separator,
                                                prefix,
                                                hostname[
                                                    'hostname'],
                                                port['port'],
                                                postfix)
                                    else:
                                        result += '{}{}{}:{}{}'.format(
                                            separator,
                                            prefix,
                                            host['ip'],
                                            port['port'],
                                            postfix)
            if result:
                result = result[len(separator):]

    elif form.filetype.data == 'csv':
        response_type = 'text/plain'
        # 'host/hostname','port', 'type', 'service', 'description'

        # always with ports

        csvfile = io.StringIO()
        csv_writer = csv.writer(csvfile, dialect='excel', delimiter=';')

        columns = ['host', 'port', 'type', 'service', 'description']
        csv_writer.writerow(columns)

        # preparation: issues

        if form.issue_name.data:
            port_ids = db.search_issues_port_ids(current_project['id'],
                                                 form.issue_name.data)

        for host in result_hosts:
            ports = db.select_host_ports(host['id'])
            hostnames = db.select_ip_hostnames(host['id'])
            for port in ports:
                if (not form.port.data) or ([port['port'], port['is_tcp']]
                                            in ports_array):
                    if form.service.data in port['service']:
                        if (not form.issue_name.data) or (
                                port['id'] in port_ids):
                            if host_export == 'ip&hostname':
                                csv_writer.writerow([host['ip'],
                                                     port['port'],
                                                     'tcp' if port[
                                                         'is_tcp'] else 'udp',
                                                     port['service'],
                                                     port['description']])
                                for hostname in hostnames:
                                    csv_writer.writerow([hostname['hostname'],
                                                         port['port'],
                                                         'tcp' if port[
                                                             'is_tcp'] else 'udp',
                                                         port['service'],
                                                         port['description']])
                            elif host_export == 'ip':
                                csv_writer.writerow([host['ip'],
                                                     port['port'],
                                                     'tcp' if port[
                                                         'is_tcp'] else 'udp',
                                                     port['service'],
                                                     port['description']])

                            elif host_export == 'hostname':
                                for hostname in hostnames:
                                    csv_writer.writerow([hostname['hostname'],
                                                         port['port'],
                                                         'tcp' if port[
                                                             'is_tcp'] else 'udp',
                                                         port['service'],
                                                         port['description']])

                            elif host_export == 'ip&hostname_unique':
                                if hostnames:
                                    for hostname in hostnames:
                                        csv_writer.writerow(
                                            [hostname['hostname'],
                                             port['port'],
                                             'tcp' if port[
                                                 'is_tcp'] else 'udp',
                                             port['service'],
                                             port['description']])
                                else:
                                    csv_writer.writerow([host['ip'],
                                                         port['port'],
                                                         'tcp' if port[
                                                             'is_tcp'] else 'udp',
                                                         port['service'],
                                                         port['description']])
        result = csvfile.getvalue()

    elif form.filetype.data == 'json' or form.filetype.data == 'xml':

        if form.filetype.data == 'xml':
            response_type = 'text/xml'
        else:
            response_type = 'application/json'

        # first generates json

        # [{"<ip>":"","hostnames":["<hostname_1",..],
        # "ports":[ {"num":"<num>", "type":"tcp", "service":"<service>",
        # "description": "<comment>"},...],},...]

        json_object = []

        # preparation: issues

        if form.issue_name.data:
            port_ids = db.search_issues_port_ids(current_project['id'],
                                                 form.issue_name.data)

        for host in result_hosts:
            ports = db.select_host_ports(host['id'])
            hostnames = db.select_ip_hostnames(host['id'])

            host_object = {}
            host_object['ip'] = host['ip']
            host_object['hostnames'] = [hostname['hostname'] for hostname in
                                        hostnames]
            host_object['ports'] = []
            for port in ports:
                if (not form.port.data) or ([port['port'], port['is_tcp']]
                                            in ports_array):
                    if form.service.data in port['service']:
                        port_object = {}
                        port_object['num'] = port['port']
                        port_object['type'] = 'tcp' if port['is_tcp'] else 'udp'
                        port_object['service'] = port['service']
                        port_object['description'] = port['description']

                        if (not form.issue_name.data) or (
                                port['id'] in port_ids):
                            host_object['ports'].append(port_object)

            if not ((not host_object['ports']) and (form.port.data or
                                                    form.service.data or
                                                    form.issue_name.data)):
                json_object.append(host_object)

        if form.filetype.data == 'xml':
            s = dicttoxml.dicttoxml(json_object)
            dom = parseString(s)
            result = dom.toprettyxml()
        else:
            result = json.dumps(json_object, sort_keys=True, indent=4)

    if form.open_in_browser.data:
        return Response(result, content_type=response_type)

    else:
        return send_file(io.BytesIO(result.encode()),
                         attachment_filename='{}.{}'.format(form.filename.data,
                                                            form.filetype.data),
                         mimetype=response_type,
                         as_attachment=True)


@routes.route('/project/<uuid:project_id>/tools/http-sniffer/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def http_sniffer(project_id, current_project, current_user):
    return render_template('project/tools/sniffers/http.html',
                           current_project=current_project,
                           tab_name='HTTP-Sniffer')


@routes.route('/project/<uuid:project_id>/tools/http-sniffer/add',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def http_sniffer_add_form(project_id, current_project, current_user):
    form = NewHTTPSniffer()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        sniffer_id = db.insert_new_http_sniffer(form.name.data, current_project['id'])
        return redirect(
            '/project/{}/tools/http-sniffer/#/sniffer_{}'.format(current_project['id'], sniffer_id))
    return redirect(
        '/project/{}/tools/http-sniffer/'.format(current_project['id']))


@routes.route(
    '/project/<uuid:project_id>/tools/http-sniffer/<uuid:sniffer_id>/edit',
    methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def http_sniffer_edit_form(project_id, current_project, current_user,
                           sniffer_id):
    # check if sniffer in project
    current_sniffer = db.select_http_sniffer_by_id(str(sniffer_id))
    if not current_sniffer or current_sniffer[0]['project_id'] != \
            current_project['id']:
        return redirect(
            '/project/{}/tools/http-sniffer/'.format(current_project['id']))

    current_sniffer = current_sniffer[0]

    form = EditHTTPSniffer()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        if form.submit.data == 'Clear':
            db.delete_http_sniffer_requests(current_sniffer['id'])
        elif form.submit.data == 'Update':
            db.update_http_sniffer(current_sniffer['id'],
                                   form.status.data,
                                   form.location.data,
                                   form.body.data)
    return redirect(
        '/project/{}/tools/http-sniffer/#/sniffer_{}'.format(current_project['id'], current_sniffer['id']))


@routes.route('/http_sniff/<uuid:sniffer_id>/', defaults={"route_path": ""},
              methods=['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT',
                       'OPTIONS', 'TRACE', 'PATCH'])
@csrf.exempt
@routes.route('/http_sniff/<uuid:sniffer_id>/<path:route_path>',
              methods=['GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'CONNECT',
                       'OPTIONS', 'TRACE', 'PATCH'])
@csrf.exempt
def http_sniffer_capture_page(sniffer_id, route_path):
    current_sniffer = db.select_http_sniffer_by_id(str(sniffer_id))

    if not current_sniffer:
        return redirect('/')

    current_sniffer = current_sniffer[0]

    http_start_header = '''{} {} {}'''.format(request.method,
                                              request.environ['RAW_URI'],
                                              request.environ[
                                                  'SERVER_PROTOCOL'])

    http_headers = str(request.headers)

    data = request.get_data().decode('charmap')

    ip = request.remote_addr

    current_time = int(time.time() * 1000)

    full_request_str = '''{}\n{}{}'''.format(http_start_header, http_headers,
                                             data)

    db.insert_new_http_sniffer_package(current_sniffer['id'], current_time,
                                       ip, full_request_str)

    if current_sniffer['location']:
        return current_sniffer['body'], current_sniffer['status'], {
            'Content-Location': current_sniffer['location'],
            'Location': current_sniffer['location'],
            'Content-Type': 'text/plain'}
    else:
        return current_sniffer['body'], current_sniffer['status'], \
               {'Content-Type': 'text/plain'}


@routes.route(
    '/project/<uuid:project_id>/tools/http-sniffer/<uuid:sniffer_id>/delete',
    methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def http_sniffer_delete_form(project_id, current_project, current_user,
                             sniffer_id):
    # check if sniffer in project
    current_sniffer = db.select_http_sniffer_by_id(str(sniffer_id))
    if not current_sniffer or current_sniffer[0]['project_id'] != \
            current_project['id']:
        return redirect(
            '/project/{}/tools/http-sniffer/'.format(current_project['id']))

    current_sniffer = current_sniffer[0]

    db.safe_delete_http_sniffer(current_sniffer['id'])
    return redirect(
        '/project/{}/tools/http-sniffer/'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/tools/ipwhois/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def ipwhois_page(project_id, current_project, current_user):
    return render_template('project/tools/scanners/ipwhois.html',
                           current_project=current_project,
                           tab_name='IPWhois')


@routes.route('/project/<uuid:project_id>/tools/ipwhois/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def ipwhois_page_form(project_id, current_project, current_user):
    form = IPWhoisForm()
    form.validate()

    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if form.ip.data:
        try:
            ip_object = ipwhois.IPWhois(form.ip.data)
            ip_data = ip_object.lookup_rdap()
            asn_num = ip_data["asn"]
            if asn_num != 'NA':
                network = ip_data["asn_cidr"]
                gateway = network.split('/')[0]
                mask = int(network.split('/')[1])
                country = ip_data["asn_country_code"]
                description = ip_data["asn_description"]
                asn_date = ip_data['asn_date']
                ip_version = ip_data["network"]["ip_version"]

                # insert_new_network(self, ip, mask, asn, comment,
                # project_id, user_id,is_ipv6):

                full_description = "Country: {}\nDate: {}\nDescription: {}".format(
                    country,
                    asn_date,
                    description)

                # check if exist

                network = db.select_network_by_ip(current_project['id'],
                                                  gateway,
                                                  mask,
                                                  ipv6=(ip_version == 'v6'))
                if not network:
                    network_id = db.insert_new_network(gateway, mask, asn_num,
                                                       full_description,
                                                       current_project['id'],
                                                       current_user['id'],
                                                       ip_version == 'v6')
                else:
                    network_id = network[0]['id']
                    db.update_network(network_id, current_project['id'], gateway, mask, asn_num,
                                      full_description, ip_version == 'v6')
                return redirect(
                    '/project/{}/networks/'.format(current_project['id']))
            else:
                errors.append('ASN does not exist!')

        except ipwhois.IPDefinedError:
            errors.append('IP was defined in standards')
        except ValueError:
            errors.append('IP was defined in standards')
    if form.hosts.data:
        for host in form.hosts.data:
            try:
                ip_object = ipwhois.IPWhois(host)
                ip_data = ip_object.lookup_rdap()
                asn_num = ip_data["asn"]
                if asn_num != 'NA':
                    network = ip_data["asn_cidr"]
                    gateway = network.split('/')[0]
                    mask = int(network.split('/')[1])
                    country = ip_data["asn_country_code"]
                    description = ip_data["asn_description"]
                    asn_date = ip_data['asn_date']
                    ip_version = ip_data["network"]["ip_version"]

                    # insert_new_network(self, ip, mask, asn, comment,
                    # project_id, user_id,is_ipv6):

                    full_description = "Country: {}\nDate: {}\nDescription: {}".format(
                        country,
                        asn_date,
                        description)

                    # check if exist

                    network = db.select_network_by_ip(current_project['id'],
                                                      gateway,
                                                      mask,
                                                      ipv6=(ip_version == 'v6'))
                    if not network:
                        network_id = db.insert_new_network(gateway, mask,
                                                           asn_num,
                                                           full_description,
                                                           current_project[
                                                               'id'],
                                                           current_user['id'],
                                                           ip_version == 'v6')
                    else:
                        network_id = network[0]['id']
                        db.update_network(network_id, current_project['id'], gateway, mask,
                                          asn_num, full_description, ip_version == 'v6')
                else:
                    errors.append('ASN does not exist!')
            except ipwhois.IPDefinedError:
                errors.append('IP was defined in standards')
            except ValueError:
                errors.append('IP was defined in standards')

    if form.networks.data:
        for host in form.networks.data:
            try:
                ip_object = ipwhois.IPWhois(host)
                ip_data = ip_object.lookup_rdap()
                asn_num = ip_data["asn"]
                if asn_num != 'NA':
                    network = ip_data["asn_cidr"]
                    gateway = network.split('/')[0]
                    mask = int(network.split('/')[1])
                    country = ip_data["asn_country_code"]
                    description = ip_data["asn_description"]
                    asn_date = ip_data['asn_date']
                    ip_version = ip_data["network"]["ip_version"]

                    # insert_new_network(self, ip, mask, asn, comment,
                    # project_id, user_id,is_ipv6):

                    full_description = "Country: {}\nDate: {}\nDescription: {}".format(
                        country,
                        asn_date,
                        description)

                    # check if exist

                    network = db.select_network_by_ip(current_project['id'],
                                                      gateway,
                                                      mask,
                                                      ipv6=(ip_version == 'v6'))
                    if not network:
                        network_id = db.insert_new_network(gateway, mask,
                                                           asn_num,
                                                           full_description,
                                                           current_project[
                                                               'id'],
                                                           current_user['id'],
                                                           ip_version == 'v6')
                    else:
                        network_id = network[0]['id']
                        db.update_network(network_id, current_project['id'], gateway, mask, asn_num,
                                          full_description, ip_version == 'v6')
                else:
                    errors.append('ASN does not exist!')
            except ipwhois.IPDefinedError:
                errors.append('IP was defined in standards')
            except ValueError:
                errors.append('Wrong ip format')

    return render_template('project/tools/scanners/ipwhois.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='IPWhois')


@routes.route('/project/<uuid:project_id>/tools/shodan/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def shodan_page(project_id, current_project, current_user):
    return render_template('project/tools/scanners/shodan.html',
                           current_project=current_project,
                           tab_name='Shodan')


@routes.route('/project/<uuid:project_id>/tools/shodan/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def shodan_page_form(project_id, current_project, current_user):
    form = ShodanForm()
    form.validate()

    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    # api_key

    shodan_api_key = form.api_key.data

    if form.api_id.data and is_valid_uuid(form.api_id.data):
        users_configs = db.select_configs(team_id='0',
                                          user_id=current_user['id'],
                                          name='shodan')

        for team in db.select_user_teams(current_user['id']):
            users_configs += db.select_configs(team_id=team['id'],
                                               user_id='0',
                                               name='shodan')

        for config in users_configs:
            if config['id'] == form.api_id.data:
                shodan_api_key = config['data']

    if not shodan_api_key:
        errors.append('Key not found!')

    shodan_api = shodan.Shodan(shodan_api_key)

    # checker
    try:
        shodan_api.host('8.8.8.8')
    except shodan.exception.APIError:
        errors.append('Wrong API Shodan key!')

    if not errors:
        if form.ip.data:
            try:
                shodan_json = shodan_api.host(form.ip.data)
                asn = int(shodan_json['asn'].replace('AS', ''))
                os_info = shodan_json['os']
                ip = shodan_json['ip_str']
                ip_version = IP(ip).version()
                asn_info = shodan_json['isp']
                coords = ''
                if 'latitude' in shodan_json:
                    coords = "lat {} long {}".format(shodan_json['latitude'],
                                                     shodan_json['longitude'])
                country = ''
                if 'country_name' in shodan_json:
                    country = shodan_json['country_name']
                city = ''
                if 'city' in shodan_json:
                    city = shodan_json['city']
                organization = shodan_json['org']

                if form.need_network.data:
                    # create network
                    net_tmp = ipwhois.net.Net('8.8.8.8')
                    asn_tmp = ipwhois.asn.ASNOrigin(net_tmp)
                    asn_full_data = asn_tmp.lookup(asn='AS{}'.format(asn))
                    for network in asn_full_data['nets']:
                        if ipaddress.ip_address(ip) in \
                                ipaddress.ip_network(network['cidr'], False):
                            cidr = network['cidr']
                            net_ip = cidr.split('/')[0]
                            net_mask = int(cidr.split('/')[1])
                            net_descr = network['description']
                            net_maintain = network['maintainer']
                            full_network_description = 'ASN info: {}\nCountry: {}\nCity: {}\nCoords: {}\nDescription: {}\nMaintainer: {}'.format(
                                asn_info, country, city,
                                coords, net_descr, net_maintain)

                            network_id = db.select_network_by_ip(
                                current_project['id'], net_ip, net_mask,
                                ip_version == 6)

                            if not network_id:
                                network_id = db.insert_new_network(net_ip,
                                                                   net_mask,
                                                                   asn,
                                                                   full_network_description,
                                                                   current_project[
                                                                       'id'],
                                                                   current_user[
                                                                       'id'],
                                                                   ip_version == 6)
                            else:
                                network_id = network_id[0]['id']
                                db.update_network(network_id, current_project['id'], net_ip, net_mask,
                                                  asn, full_network_description, ip_version == 6)

                # create host
                full_host_description = "Country: {}\nCity: {}\nOrganization: {}".format(
                    country, city, organization)
                # hostnames = shodan_json["hostnames"]

                host_id = db.select_project_host_by_ip(
                    current_project['id'],
                    ip)
                if host_id:
                    host_id = host_id[0]['id']
                    db.update_host_description(host_id,
                                               full_host_description)
                else:
                    host_id = db.insert_host(current_project['id'],
                                             ip,
                                             current_user['id'],
                                             full_host_description)
                # add hostnames
                for hostname in shodan_json["hostnames"]:
                    hostname_obj = db.select_ip_hostname(host_id, hostname)
                    if not hostname_obj:
                        hostname_id = db.insert_hostname(host_id,
                                                         hostname,
                                                         'Added from Shodan',
                                                         current_user['id'])

                # add ports with cve
                for port in shodan_json['data']:
                    product = ''
                    if 'product' in port:
                        product = port['product']
                    is_tcp = (port['transport'] == 'tcp')
                    port_num = int(port['port'])
                    port_info = ''
                    protocol = port['_shodan']["module"]
                    if 'info' in port:
                        port_info = port['info']

                    full_port_info = "Product: {}\nInfo: {}".format(
                        product,
                        port_info
                    )

                    port_id = db.select_ip_port(host_id, port_num,
                                                is_tcp=is_tcp)

                    if port_id:
                        port_id = port_id[0]['id']
                        db.update_port_proto_description(port_id,
                                                         protocol,
                                                         full_port_info)
                    else:
                        port_id = db.insert_host_port(host_id, port_num,
                                                      is_tcp,
                                                      protocol,
                                                      full_port_info,
                                                      current_user['id'],
                                                      current_project['id'])

                    # add vulnerabilities
                    if "vulns" in port:
                        vulns = port['vulns']
                        for cve in vulns:
                            cvss = vulns[cve]['cvss']
                            summary = vulns[cve]['summary']
                            services = {port_id: ["0"]}

                            issue_id = db.insert_new_issue(cve, summary, '',
                                                           cvss,
                                                           current_user[
                                                               'id'],
                                                           services,
                                                           'need to check',
                                                           current_project[
                                                               'id'],
                                                           cve=cve)

            except shodan.exception.APIError as e:
                errors.append(e)
            except ValueError:
                errors.append('Wrong ip!')
        elif form.hosts.data:
            for host in form.hosts.data.split(','):
                try:
                    shodan_json = shodan_api.host(host)
                    asn = int(shodan_json['asn'].replace('AS', ''))
                    os_info = shodan_json['os']
                    ip = shodan_json['ip_str']
                    ip_version = IP(ip).version()
                    asn_info = shodan_json['isp']
                    coords = ''
                    if 'latitude' in shodan_json:
                        coords = "lat {} long {}".format(
                            shodan_json['latitude'],
                            shodan_json['longitude'])
                    country = ''
                    if 'country_name' in shodan_json:
                        country = shodan_json['country_name']
                    city = ''
                    if 'city' in shodan_json:
                        city = shodan_json['city']
                    organization = shodan_json['org']

                    if form.need_network.data:
                        # create network
                        net_tmp = ipwhois.net.Net('8.8.8.8')
                        asn_tmp = ipwhois.asn.ASNOrigin(net_tmp)
                        asn_full_data = asn_tmp.lookup(asn='AS{}'.format(asn))
                        for network in asn_full_data['nets']:
                            if ipaddress.ip_address(ip) in \
                                    ipaddress.ip_network(network['cidr'],
                                                         False):
                                cidr = network['cidr']
                                net_ip = cidr.split('/')[0]
                                net_mask = int(cidr.split('/')[1])
                                net_descr = network['description']
                                net_maintain = network['maintainer']
                                full_network_description = 'ASN info: {}\nCountry: {}\nCity: {}\nCoords: {}\nDescription: {}\nMaintainer: {}'.format(
                                    asn_info, country, city,
                                    coords, net_descr, net_maintain)

                                network_id = db.select_network_by_ip(
                                    current_project['id'], net_ip, net_mask,
                                    ip_version == 6)

                                if not network_id:
                                    network_id = db.insert_new_network(net_ip,
                                                                       net_mask,
                                                                       asn,
                                                                       full_network_description,
                                                                       current_project[
                                                                           'id'],
                                                                       current_user[
                                                                           'id'],
                                                                       ip_version == 6)
                                else:
                                    network_id = network_id[0]['id']
                                    db.update_network(network_id, current_project['id'], net_ip, net_mask,
                                                      asn, full_network_description, ip_version == 6)

                    # create host
                    full_host_description = "Country: {}\nCity: {}\nOS: {}\nOrganization: {}".format(
                        country, city, organization)
                    # hostnames = shodan_json["hostnames"]

                    host_id = db.select_project_host_by_ip(
                        current_project['id'],
                        ip)
                    if host_id:
                        host_id = host_id[0]['id']
                        db.update_host_description(host_id,
                                                   full_host_description)
                    else:
                        host_id = db.insert_host(current_project['id'],
                                                 ip,
                                                 current_user['id'],
                                                 full_host_description)
                    if os_info:
                        db.update_host_os(host_id, os_info)
                    # add hostnames
                    for hostname in shodan_json["hostnames"]:
                        hostname_obj = db.select_ip_hostname(host_id, hostname)
                        if not hostname_obj:
                            hostname_id = db.insert_hostname(host_id,
                                                             hostname,
                                                             'Added from Shodan',
                                                             current_user['id'])

                    # add ports with cve
                    for port in shodan_json['data']:
                        product = ''
                        if 'product' in port:
                            product = port['product']
                        is_tcp = (port['transport'] == 'tcp')
                        port_num = int(port['port'])
                        port_info = ''
                        protocol = port['_shodan']["module"]
                        if 'info' in port:
                            port_info = port['info']

                        full_port_info = "Product: {}\nInfo: {}".format(
                            product,
                            port_info
                        )

                        port_id = db.select_ip_port(host_id, port_num,
                                                    is_tcp=is_tcp)

                        if port_id:
                            port_id = port_id[0]['id']
                            db.update_port_proto_description(port_id,
                                                             protocol,
                                                             full_port_info)
                        else:
                            port_id = db.insert_host_port(host_id, port_num,
                                                          is_tcp,
                                                          protocol,
                                                          full_port_info,
                                                          current_user['id'],
                                                          current_project['id'])

                        # add vulnerabilities
                        if "vulns" in port:
                            vulns = port['vulns']
                            for cve in vulns:
                                cvss = vulns[cve]['cvss']
                                summary = vulns[cve]['summary']
                                services = {port_id: ["0"]}

                                issue_id = db.insert_new_issue(cve, summary, '',
                                                               cvss,
                                                               current_user[
                                                                   'id'],
                                                               services,
                                                               'need to check',
                                                               current_project[
                                                                   'id'],
                                                               cve=cve)
                except shodan.exception.APIError as e:
                    errors.append(e)
                except ValueError:
                    errors.append('Wrong ip!')
                time.sleep(1.1)  # shodan delay

        elif form.networks.data:
            for network_id in form.networks.data.split(','):
                if is_valid_uuid(network_id):
                    current_network = db.select_network(network_id)
                    if current_network and current_network[0]['asn'] and \
                            current_network[0]['asn'] > 0:
                        asn = int(current_network[0]['asn'])

                        result = shodan_api.search('asn:AS{}'.format(asn),
                                                   limit=1000)
                        for shodan_json in result['matches']:
                            try:
                                os_info = shodan_json['os']
                                ip = shodan_json['ip_str']
                                ip_version = IP(ip).version()
                                asn_info = shodan_json['isp']
                                coords = ''
                                if 'latitude' in shodan_json:
                                    coords = "lat {} long {}".format(
                                        shodan_json['latitude'],
                                        shodan_json['longitude'])
                                country = ''
                                if 'country_name' in shodan_json:
                                    country = shodan_json['country_name']
                                city = ''
                                if 'city' in shodan_json:
                                    city = shodan_json['city']
                                organization = shodan_json['org']

                                if form.need_network.data:
                                    # create network
                                    net_tmp = ipwhois.net.Net('8.8.8.8')
                                    asn_tmp = ipwhois.asn.ASNOrigin(net_tmp)
                                    asn_full_data = asn_tmp.lookup(
                                        asn='AS{}'.format(asn))
                                    for network in asn_full_data['nets']:
                                        if ipaddress.ip_address(ip) in \
                                                ipaddress.ip_network(
                                                    network['cidr'],
                                                    False):
                                            cidr = network['cidr']
                                            net_ip = cidr.split('/')[0]
                                            net_mask = int(cidr.split('/')[1])
                                            net_descr = network['description']
                                            net_maintain = network['maintainer']
                                            full_network_description = 'ASN info: {}\nCountry: {}\nCity: {}\nCoords: {}\nDescription: {}\nMaintainer: {}'.format(
                                                asn_info, country, city,
                                                coords, net_descr, net_maintain)

                                            network_id = db.select_network_by_ip(
                                                current_project['id'], net_ip,
                                                net_mask,
                                                ip_version == 6)

                                            if not network_id:
                                                network_id = db.insert_new_network(
                                                    net_ip,
                                                    net_mask,
                                                    asn,
                                                    full_network_description,
                                                    current_project[
                                                        'id'],
                                                    current_user[
                                                        'id'],
                                                    ip_version == 6)
                                            else:
                                                network_id = network_id[0]['id']
                                                db.update_network(network_id,
                                                                  current_project['id'],
                                                                  net_ip,
                                                                  net_mask,
                                                                  asn,
                                                                  full_network_description,
                                                                  ip_version == 6)

                                # create host
                                full_host_description = "Country: {}\nCity: {}\nOS: {}\nOrganization: {}".format(
                                    country, city, os_info, organization)
                                # hostnames = shodan_json["hostnames"]

                                host_id = db.select_project_host_by_ip(
                                    current_project['id'],
                                    ip)
                                if host_id:
                                    host_id = host_id[0]['id']
                                    db.update_host_description(host_id,
                                                               full_host_description)
                                else:
                                    host_id = db.insert_host(
                                        current_project['id'],
                                        ip,
                                        current_user['id'],
                                        full_host_description)
                                # add hostnames
                                for hostname in shodan_json["hostnames"]:
                                    hostname_obj = db.select_ip_hostname(
                                        host_id, hostname)
                                    if not hostname_obj:
                                        hostname_id = db.insert_hostname(
                                            host_id,
                                            hostname,
                                            'Added from Shodan',
                                            current_user['id'])

                                # add ports with cve
                                port_num = int(shodan_json['port'])
                                product = ''
                                if 'product' in shodan_json:
                                    product = shodan_json['product']
                                is_tcp = int(shodan_json['transport'] == 'tcp')
                                port_info = ''
                                protocol = shodan_json['_shodan']["module"]
                                if 'info' in shodan_json:
                                    port_info = shodan_json['info']

                                full_port_info = "Product: {}\nInfo: {}".format(
                                    product,
                                    port_info
                                )

                                port_id = db.select_ip_port(host_id,
                                                            port_num,
                                                            is_tcp=is_tcp)

                                if port_id:
                                    port_id = port_id[0]['id']
                                    db.update_port_proto_description(
                                        port_id,
                                        protocol,
                                        full_port_info)
                                else:
                                    port_id = db.insert_host_port(host_id,
                                                                  port_num,
                                                                  is_tcp,
                                                                  protocol,
                                                                  full_port_info,
                                                                  current_user[
                                                                      'id'],
                                                                  current_project[
                                                                      'id'])

                                # add vulnerabilities
                                if "vulns" in shodan_json:
                                    vulns = shodan_json['vulns']
                                    for cve in vulns:
                                        cvss = vulns[cve]['cvss']
                                        summary = vulns[cve]['summary']
                                        services = {port_id: ["0"]}

                                        issue_id = db.insert_new_issue(cve,
                                                                       summary,
                                                                       '',
                                                                       cvss,
                                                                       current_user[
                                                                           'id'],
                                                                       services,
                                                                       'need to check',
                                                                       current_project[
                                                                           'id'],
                                                                       cve=cve)
                            except shodan.exception.APIError as e:
                                pass  # a lot of errors
                            except ValueError:
                                pass  # a lot of errors
                            time.sleep(1.1)  # shodan delay
    return render_template('project/tools/scanners/shodan.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='Shodan')


@routes.route('/project/<uuid:project_id>/tools/checkmarx/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def checkmarx_page(project_id, current_project, current_user):
    return render_template('project/tools/import/checkmarx.html',
                           current_project=current_project,
                           tab_name='Checkmarx')


@routes.route('/project/<uuid:project_id>/tools/checkmarx/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def checkmarx_page_form(project_id, current_project, current_user):
    form = CheckmaxForm()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:

        # xml files
        for file in form.xml_files.data:
            if file.filename:
                scan_result = BeautifulSoup(file.read(),
                                            "html.parser")
                query_list = scan_result.find_all("query")
                for query in query_list:
                    vulnerability_name = re.sub(' Version:[0-9]+', '', query.attrs['querypath'].split('\\')[-1])
                    language = query.attrs['language']
                    cwe = query.attrs['cweid']
                    vuln_array = query.find_all("result")
                    for vuln_example in vuln_array:
                        criticality = vuln_example.attrs['severity']  # High
                        filename = vuln_example.attrs['filename']
                        path_find = vuln_example.find_all("path")
                        paths_str_arrays = []
                        for path_obj in path_find:
                            paths_str = ''
                            path_nodes = vuln_example.find_all("pathnode")
                            if path_nodes:
                                paths_str = '########## Path {} ###########\n'.format(path_find.index(path_obj) + 1)
                            for path_node in path_nodes:
                                filename = path_node.find_all("filename")[0].text
                                line_num = int(path_node.find_all("line")[0].text)
                                colum_num = int(path_node.find_all("column")[0].text)
                                code_arr = path_node.find_all("code")
                                node_str = 'Filename: {}\nLine: {} Column: {}'.format(filename, line_num, colum_num)
                                for code in code_arr:
                                    node_str += '\n' + code.text.strip(' \t')
                                paths_str += node_str + '\n\n'

                            if paths_str:
                                paths_str_arrays.append(paths_str + '\n\n')
                        all_paths_str = '\n'.join(paths_str_arrays)

                        if criticality == 'High':
                            cvss = 9.5
                        elif criticality == 'Medium':
                            cvss = 8.0
                        elif criticality == 'Low':
                            cvss = 2.0
                        else:
                            cvss = 0
                        issue_id = db.insert_new_issue(vulnerability_name,
                                                       'Language: {}\n'.format(language) + all_paths_str, filename,
                                                       cvss, current_user['id'],
                                                       {}, 'need to check', current_project['id'], cwe=cwe,
                                                       issue_type='custom')
    return render_template('project/tools/import/checkmarx.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='Checkmarx')


@routes.route('/project/<uuid:project_id>/tools/depcheck/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def depcheck_page(project_id, current_project, current_user):
    return render_template('project/tools/import/depcheck.html',
                           current_project=current_project,
                           tab_name='DepCheck')


@routes.route('/project/<uuid:project_id>/tools/depcheck/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def depcheck_page_form(project_id, current_project, current_user):
    form = Depcheck()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        for file in form.xml_files.data:
            if file.filename:
                scan_result = BeautifulSoup(file.read(),
                                            "html.parser")
                query_list = scan_result.find_all("dependency")
                for query in query_list:

                    filename = query.find("filename").text
                    filepath = query.find("filepath").text

                    vuln_array = query.find_all("vulnerability")
                    for vuln_example in vuln_array:
                        name = vuln_example.find('name').text
                        cve = ''
                        if name.startswith('CVE'):
                            cve = name
                        cvss_obj = vuln_example.find('cvssv3')
                        if cvss_obj:
                            cvss = float(cvss_obj.find('basescore').text)
                        elif vuln_example.find('cvssscore'):
                            cvss = float(vuln_example.find('cvssscore').text)
                        elif vuln_example.find('cvssv2'):
                            cvss = float(vuln_example.find('cvssv2').find('score').text)
                        else:
                            cvss = 0
                        cwes = vuln_example.find_all("cwe")
                        cwe = 0
                        if cwes:
                            cwe = int(cwes[0].text.replace('CWE-', '').split(' ')[0])
                        description = vuln_example.find('description').text
                        soft_search = vuln_example.find_all("software")
                        software_arr = []
                        for path_obj in soft_search:
                            s = str(path_obj.text)
                            versions = ''
                            if 'versionstartincluding' in path_obj.attrs:
                                versions += str(path_obj.attrs['versionstartincluding']) + '<=x'
                            if 'versionstartexcluding' in path_obj.attrs:
                                versions += str(path_obj.attrs['versionendexcluding']) + '<x'
                            if 'versionendincluding' in path_obj.attrs:
                                versions += '<=' + str(path_obj.attrs['versionendincluding'])
                            if 'versionendexcluding' in path_obj.attrs:
                                versions += '<' + str(path_obj.attrs['versionendexcluding'])

                            if versions:
                                s += ' versions ({})'.format(versions)
                            software_arr.append(s)

                        all_software_str = '\n\n'.join(software_arr)

                        full_description = 'File: ' + filepath + '\n\n' + description \
                                           + '\n\nVulnerable versions: \n' + all_software_str

                        issue_id = db.insert_new_issue(name, full_description, filepath, cvss, current_user['id'],
                                                       '{}', 'need to recheck', current_project['id'], cve, cwe,
                                                       'custom', '', filename)
    return render_template('project/tools/import/depcheck.html',
                           current_project=current_project,
                           tab_name='DepCheck',
                           errors=errors)


@routes.route('/project/<uuid:project_id>/tools/openvas/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def openvas_page(project_id, current_project, current_user):
    return render_template('project/tools/import/openvas.html',
                           current_project=current_project,
                           tab_name='OpenVAS')


@routes.route('/project/<uuid:project_id>/tools/openvas/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def openvas_page_form(project_id, current_project, current_user):
    form = Depcheck()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        for file in form.xml_files.data:
            if file.filename:
                scan_result = BeautifulSoup(file.read(),
                                            "html.parser")
                query_list = scan_result.find_all("result")
                for query in query_list:
                    issue_host = query.find('host').text.split('\n')[0]
                    issue_hostname = query.find('host').find('hostname').text
                    issue_port = int(query.find('port').text.split('/')[0])
                    issue_is_tcp = int(query.find('port').text.split('/')[1] == 'tcp')

                    nvt_obj = query.find('nvt')
                    issue_name = nvt_obj.find('name').text
                    issue_type = nvt_obj.find('family').text
                    issue_cvss = float(nvt_obj.find('cvss_base').text)
                    issue_long_description = nvt_obj.find('tags').text

                    solution_obj = nvt_obj.find('solution')
                    issue_solution = ''
                    if solution_obj.get('type') != 'WillNotFix':
                        issue_solution = solution_obj.text

                    refs_objects = nvt_obj.find('refs')
                    refs_objects = refs_objects.findAll('ref')
                    cve_list = []
                    links_list = []
                    for ref_obj in refs_objects:
                        if ref_obj.get('type') == 'url':
                            links_list.append(ref_obj.get('id'))
                        if ref_obj.get('type') == 'cve':
                            cve_list.append(ref_obj.get('id'))

                    issue_short_description = query.find('description').text

                    # check if host exists

                    host_id = db.select_project_host_by_ip(current_project['id'], issue_host)
                    if not host_id:
                        host_id = db.insert_host(current_project['id'], issue_host,
                                                 current_user['id'], 'Added from OpenVAS')
                    else:
                        host_id = host_id[0]['id']

                    # check if port exists
                    port_id = db.select_host_port(host_id, issue_port, issue_is_tcp)
                    if not port_id:
                        port_id = db.insert_host_port(host_id, issue_port, issue_is_tcp, 'unknown', '',
                                                      current_user['id'], current_project['id'])
                    else:
                        port_id = port_id[0]['id']

                    # check if hostname exists
                    hostname_id = ''
                    if issue_hostname != '':
                        hostname_id = db.select_ip_hostname(host_id, issue_hostname)
                        if not hostname_id:
                            hostname_id = db.insert_hostname(host_id, issue_hostname,
                                                             'Added from OpenVAS', current_user['id'])
                        else:
                            hostname_id = hostname_id[0]['id']

                    full_description = 'Short description: \n{}\n\nFull description:\n{}'.format(
                        issue_short_description,
                        issue_long_description)
                    cve_str = ','.join(cve_list)
                    if links_list:
                        full_description += '\n\nLinks:\n' + '\n'.join(links_list)
                    services = {
                        port_id: [hostname_id] if hostname_id else ['0']
                    }
                    db.insert_new_issue_no_dublicate(issue_name, full_description, '', issue_cvss, current_user['id'],
                                                     services, 'need to recheck', current_project['id'], cve_str,
                                                     0, 'custom', issue_solution, '')

    return render_template('project/tools/import/openvas.html',
                           current_project=current_project,
                           tab_name='OpenVAS',
                           errors=errors)


@routes.route('/project/<uuid:project_id>/tools/netsparker/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def netsparker_page(project_id, current_project, current_user):
    return render_template('project/tools/import/netsparker.html',
                           current_project=current_project,
                           tab_name='NetSparker')


@routes.route('/project/<uuid:project_id>/tools/netsparker/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def netsparker_page_form(project_id, current_project, current_user):
    def beautify_output(xml_str):
        if xml_str == '  ': xml_str = ''
        xml_str = xml_str.replace('<p>', '\t').replace('</p>', '\n')
        xml_str = xml_str.replace('<li>', '* ').replace('</li>', '\n')
        xml_str = xml_str.replace('<ol>', '\n').replace('</ol>', '\n')
        xml_str = xml_str.replace('<div>', '').replace('</div>', '\n')
        xml_str = xml_str.replace("<a target='_blank' href='", '').replace("'><i class='icon-external-link'></i>",
                                                                           ' - ')
        xml_str = xml_str.replace('<ul>', '').replace('</ul>', '')
        xml_str = xml_str.replace('</a>', '\n')
        return xml_str

    form = Netsparker()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        for file in form.xml_files.data:
            if file.filename:
                scan_result = BeautifulSoup(file.read(),
                                            "html.parser")
                query_list = scan_result.find_all("vulnerability")

                for vuln in query_list:
                    is_confirmed = vuln.get('confirmed') == 'True'
                    if is_confirmed or (not form.only_confirmed):
                        vuln_url = vuln.find('url').text
                        vuln_name = 'Netsparker: ' + vuln.find('type').text
                        vuln_severity = vuln.find('severity').text  # High, Medium, Low, Information, BestPractice
                        vuln_description = beautify_output(vuln.find('description').text)
                        vuln_impact = beautify_output(vuln.find('impact').text)
                        vuln_fix = beautify_output(vuln.find('actionstotake').text)
                        vuln_fix1 = beautify_output(vuln.find('remedy').text)
                        vuln_skills = beautify_output(vuln.find('requiredskillsforexploitation').text)
                        vuln_links = beautify_output(vuln.find('externalreferences').text)
                        vuln_fix1_links = beautify_output(vuln.find('remedyreferences').text)
                        vuln_request = beautify_output(vuln.find('rawrequest').text)
                        vuln_response = beautify_output(vuln.find('rawresponse').text)
                        vuln_poc = beautify_output(vuln.find('proofofconcept').text)

                        vuln_path = ''
                        vuln_args = ''
                        # parse info
                        info_list = vuln.find('extrainformation').findAll('info')
                        for info_obj in info_list:
                            info_name = info_obj.get('name')
                            if info_name == 'ParserAnalyzerEngine_InputName':
                                vuln_args += ', (Input) ' + info_name
                            elif info_name == 'ParserAnalyzerEngine_FormTargetAction':
                                vuln_path = info_name
                            elif info_name == 'ParserAnalyzerEngine_IdentifiedFieldName':
                                vuln_args += ', (Input) ' + info_name
                            elif info_name == 'CookieAnalyzerEngine_IdentifiedCookies':
                                vuln_args += ', (Cookie) ' + info_name
                            elif info_name == 'ExtractedVersion':
                                vuln_description += '\n\nExtracted version: ' + info_name
                            elif info_name == 'IdentifiedErrorMessage':
                                vuln_description += '\n\nError message: \n' + info_name
                            elif info_name == 'ExtractedIPAddresses':
                                vuln_description += '\n\nExtracted IP: ' + info_name
                            elif info_name == 'CustomField_FormAction':
                                vuln_path = info_name
                            elif info_name == 'ParserAnalyzerEngine_ExternalLinks':
                                vuln_description += '\n\nExternal links: \n' + info_name
                            elif info_name == 'ParserAnalyzerEngine_FormName':
                                vuln_args += ', (Form) ' + info_name
                            elif info_name == 'EmailDisclosure_EmailAddresses':
                                vuln_description += '\n\nFound email: ' + info_name
                            elif info_name == 'Options_Allowed_Methods':
                                vuln_description += '\n\nAllowed methods: ' + info_name
                            elif info_name == 'ParserAnalyzerEngine_FormTargetAction':
                                vuln_description = '\n\nInternal path: ' + info_name

                        vuln_cwe = vuln.find('classification').find('cwe').text
                        if not vuln_cwe: vuln_cwe = 0
                        vuln_cvss = 0
                        classification_obj = vuln.find('classification')
                        if classification_obj.find('cvss'):
                            for cvss_obj in classification_obj.find('cvss').findAll('score'):
                                if cvss_obj.find('type').text == 'Base':
                                    vuln_cvss = float(cvss_obj.find('value').text)

                        # parse url

                        splitted_url = urllib.parse.urlsplit(vuln_url)
                        vuln_scheme = splitted_url.scheme
                        if not vuln_scheme:
                            vuln_scheme = 'http'
                        vuln_host_unverified = splitted_url.hostname
                        vuln_path_unverified = splitted_url.path
                        vuln_port = splitted_url.port
                        if not vuln_port:
                            if vuln_scheme == 'https':
                                vuln_port = 443
                            elif vuln_scheme == 'ftp':
                                vuln_port = 21
                            else:
                                vuln_port = 80
                        vuln_port = int(vuln_port)
                        if not vuln_path:
                            vuln_path = vuln_path_unverified
                        is_ip = False
                        vuln_host = ''
                        vuln_hostname = ''
                        try:
                            vuln_host = str(ipaddress.ip_address(vuln_host_unverified))
                        except ValueError:
                            vuln_hostname = vuln_host_unverified

                        if not vuln_host and vuln_hostname:
                            try:
                                vuln_host = str(socket.gethostbyname(vuln_host_unverified))
                            except:
                                pass

                        hostname_id = ''
                        port_id = ''
                        host_id = ''
                        if vuln_host:
                            dublicate_host = db.select_project_host_by_ip(current_project['id'], vuln_host)

                            if not dublicate_host:
                                host_id = db.insert_host(current_project['id'],
                                                         vuln_host,
                                                         current_user['id'],
                                                         'Added from Netsparker')
                            else:
                                host_id = dublicate_host[0]['id']

                            # add port

                            dublicate_port = db.select_host_port(host_id, vuln_port, True)
                            if not dublicate_port:
                                port_id = db.insert_host_port(host_id, vuln_port, True,
                                                              vuln_scheme, 'Added from Netsparker',
                                                              current_user['id'], current_project['id'])
                            else:
                                port_id = dublicate_port[0]['id']

                            # add hostname

                            if vuln_hostname:
                                dublicate_hostname = db.select_ip_hostname(host_id, vuln_hostname)
                                if not dublicate_hostname:
                                    hostname_id = db.insert_hostname(host_id, vuln_hostname,
                                                                     'Added from Netsparker',
                                                                     current_user['id'])
                                else:
                                    hostname_id = dublicate_hostname[0]['id']

                        # add issue

                        full_description = 'URL: {}\n\nDescription: \n{}\n\n'.format(vuln_url, vuln_description)
                        if vuln_impact:
                            full_description += 'Impact: ' + vuln_impact + '\n\n'
                        if vuln_skills:
                            full_description += 'Skills: ' + vuln_skills + '\n\n'
                        if vuln_poc:
                            full_description += 'PoC: ' + vuln_poc + '\n\n'
                        if vuln_links:
                            full_description += 'Links: \n' + vuln_links + '\n\n'

                        full_fix = 'Actions: ' + vuln_fix + '\n Fix:' + vuln_fix1 + '\n Links: ' + vuln_fix1_links

                        services = {}
                        if hostname_id:
                            services[port_id] = [hostname_id]
                        elif port_id:
                            services[port_id] = ["0"]

                        issue_id = db.insert_new_issue_no_dublicate(vuln_name, full_description,
                                                                    vuln_path, vuln_cvss,
                                                                    current_user['id'],
                                                                    services,
                                                                    'need to recheck',
                                                                    current_project['id'],
                                                                    '', vuln_cwe, 'web', full_fix, vuln_args)
                        # create PoC
                        poc_text = vuln_request + vuln_response
                        poc_text = poc_text.replace('\r', '')
                        poc_id = db.insert_new_poc(port_id if port_id else "0",
                                                   'Added from Netsparker',
                                                   'text',
                                                   'HTTP.txt',
                                                   issue_id,
                                                   current_user['id'],
                                                   hostname_id if hostname_id else '0', )
                        file_path = './static/files/poc/{}'.format(poc_id)
                        file_object = open(file_path, 'w')
                        file_object.write(poc_text)
                        file_object.close()

    return render_template('project/tools/import/netsparker.html',
                           current_project=current_project,
                           tab_name='NetSparker',
                           errors=errors)


@routes.route('/project/<uuid:project_id>/tools/qualys/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def qualys_page(project_id, current_project, current_user):
    return render_template('project/tools/import/qualys.html',
                           current_project=current_project,
                           tab_name='Qualys')


@routes.route('/project/<uuid:project_id>/tools/qualys/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def qualys_form(project_id, current_project, current_user):
    def beautify_output(xml_str):
        xml_str = xml_str.replace('<p>', '\t').replace('<P>', '\t')
        xml_str = xml_str.replace('<BR>', '\n').replace('</p>', '\n')
        return xml_str

    form = QualysForm()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        # xml files
        for file in form.xml_files.data:
            if file.filename:
                scan_result = BeautifulSoup(file.read(),
                                            "html.parser")
                hosts_list = scan_result.find_all("ip")
                for host in hosts_list:
                    host_id = ''
                    hostname = ''
                    ip = host.attrs['value']
                    tmp_host = db.select_project_host_by_ip(current_project['id'], ip)
                    if tmp_host:
                        host_id = tmp_host[0]['id']
                    if 'name' in host.attrs and ip != host.attrs['name']:
                        hostname = host.attrs['name']
                    # TODO: dont forget to add hostname
                    if form.add_empty_host and not host_id:
                        host_id = db.insert_host(current_project['id'], ip, current_user['id'], 'Added from Qualys')
                    ports_list = host.find('services')
                    for port_obj in ports_list.findAll('cat'):
                        if 'port' in port_obj.attrs and 'protocol' in port_obj.attrs:
                            if not host_id:
                                host_id = db.insert_host(current_project['id'], ip, current_user['id'], 'Added from Qualys')

                            port = int(port_obj.attrs['port'])
                            is_tcp = int(port_obj.attrs['protocol'] == 'tcp')
                            service = port_obj.attrs['value']

                            port_id = db.select_host_port(host_id, port, is_tcp)
                            if port_id:
                                port_id = port_id[0]['id']
                                db.update_port_service(port_id, service)
                            else:
                                port_id = db.insert_host_port(host_id, port, is_tcp, service, 'Added from Qualys',
                                                              current_user['id'], current_project['id'])

                    issues_list = host.find('vulns')
                    for issue_obj in issues_list.findAll('cat'):
                        if not host_id:
                            host_id = db.insert_host(current_project['id'], ip, current_user['id'], 'Added from Qualys')
                        port_num = 0
                        is_tcp = 1
                        if 'port' in issue_obj.attrs and 'protocol' in issue_obj.attrs:
                            port_num = int(issue_obj.attrs['port'])
                            is_tcp = int(issue_obj.attrs['protocol'] == 'tcp')

                        port_id = db.select_host_port(host_id, port_num, is_tcp)
                        if not port_id:
                            port_id = db.insert_host_port(host_id, port_num, is_tcp, 'unknown', 'Added from Qualys',
                                                          current_user['id'], current_project['id'])
                        else:
                            port_id = port_id[0]['id']
                        cvss = 0
                        cvss_tmp = issue_obj.find('cvss3_base').text
                        if not cvss_tmp or cvss_tmp == '-':
                            cvss_tmp = issue_obj.find('cvss3_temporal').text
                            if not cvss_tmp or cvss_tmp == '-':
                                cvss_tmp = issue_obj.find('cvss_temporal').text
                                if cvss_tmp and cvss_tmp != '-':
                                    cvss = float(cvss)
                            else:
                                cvss = float(cvss_tmp)
                        else:
                            cvss = float(cvss_tmp)

                        issue_name = issue_obj.find('title').text
                        issue_diagnostic = issue_obj.find('diagnosis').text
                        issue_description = issue_obj.find('consequence').text
                        issue_solution = beautify_output(issue_obj.find('solution').text)

                        # TODO: add PoC
                        issue_output = issue_obj.find('result')
                        try:
                            issue_output = issue_obj.find('result').text
                        except AttributeError:
                            issue_output = ''

                        issue_full_description = 'Diagnosis: \n{} \n\nConsequence: \n{}'.format(issue_diagnostic, issue_description)
                        issue_full_description = beautify_output(issue_full_description)
                        services = {port_id: ['0']}
                        issue_id = db.insert_new_issue_no_dublicate(issue_name, issue_full_description, '', cvss, current_user['id'], services, 'need to recheck',
                                                                    current_project['id'], '', 0, 'custom', issue_solution, '')

                    issues_list = host.find('practices')

                    for issue_obj in issues_list.findAll('practice'):
                        if not host_id:
                            host_id = db.insert_host(current_project['id'], ip, current_user['id'], 'Added from Qualys')
                        issue_сve = ''
                        if 'cveid' in issue_obj.attrs:
                            cve = issue_obj.attrs['cveid']

                        issue_name = issue_obj.find('title').text
                        issue_diagnostic = issue_obj.find('diagnosis').text
                        issue_description = issue_obj.find('consequence').text
                        issue_solution = beautify_output(issue_obj.find('solution').text)
                        # TODO: add PoC
                        issue_output = issue_obj.find('result')
                        try:
                            issue_output = issue_obj.find('result').text
                        except AttributeError:
                            issue_output = ''
                        issue_full_description = 'Diagnosis: \n{} \n\nConsequence: \n{}'.format(issue_diagnostic, issue_description)

                        issue_full_description = beautify_output(issue_full_description)

                        issue_links = []

                        for url in issue_obj.findAll('url'):
                            issue_links.append(url.text)
                        for url in issue_obj.findAll('link'):
                            issue_links.append(url.text)

                        if issue_links:
                            issue_full_description += '\n\nLinks:\n' + '\n'.join(['- ' + url for url in issue_links])

                        cvss = 0
                        cvss_tmp = issue_obj.find('cvss3_base').text
                        if not cvss_tmp or cvss_tmp == '-':
                            cvss_tmp = issue_obj.find('cvss3_temporal').text
                            if not cvss_tmp or cvss_tmp == '-':
                                cvss_tmp = issue_obj.find('cvss_temporal').text
                                if cvss_tmp and cvss_tmp != '-':
                                    cvss = float(cvss)
                            else:
                                cvss = float(cvss_tmp)
                        else:
                            cvss = float(cvss_tmp)

                        # try to detect port
                        port = 0
                        is_tcp = 1

                        info_str = issue_output.split('\n')[0]
                        if ' detected on port ' in info_str:
                            port = int(info_str.split(' detected on port ')[1].split(' ')[0])
                            if ' over ' in info_str.split(' detected on port ')[1]:
                                is_tcp = int(info_str.split(' detected on port ')[1].split(' over ')[1].split(' ')[0] == 'TCP')

                        port_id = db.select_host_port(host_id, port, is_tcp)
                        if not port_id:
                            port_id = db.insert_host_port(host_id, port, is_tcp, 'unknown', 'Added from Qualys',
                                                          current_user['id'], current_project['id'])
                        else:
                            port_id = port_id[0]['id']
                        services = {port_id: ['0']}
                        issue_id = db.insert_new_issue_no_dublicate(issue_name, issue_full_description, cve, cvss, current_user['id'], services, 'need to recheck',
                                                                    current_project['id'], '', 0, 'custom', issue_solution, '')

    return render_template('project/tools/import/qualys.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='Qualys')


@routes.route('/project/<uuid:project_id>/tools/whois/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def whois_page(project_id, current_project, current_user):
    return render_template('project/tools/scanners/whois.html',
                           current_project=current_project,
                           tab_name='Whois')


@routes.route('/project/<uuid:project_id>/tools/whois/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def whois_page_form(project_id, current_project, current_user):
    form = WhoisForm()
    form.validate()

    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        if form.host_id.data and is_valid_uuid(form.host_id.data):
            host = db.select_project_host(current_project['id'], form.host_id.data)
            if not host:
                errors.append('Host not found!')
            else:
                host_id = host[0]['id']
                hostname = db.select_ip_hostname(host_id, form.hostname.data)
                if not hostname:
                    errors.append('Hostname not found!')
                else:
                    hostname_id = hostname[0]['id']

    if not errors:
        if form.host_id.data:
            whois_obj = whois.whois(form.hostname.data)
            result_str = ''
            if 'registrar' in whois_obj and whois_obj['registrar']:
                result_str += 'Registrar: {}\n'.format(whois_obj['registrar'])
            if 'whois_server' in whois_obj and whois_obj['whois_server']:
                result_str += 'Whois server: {}\n'.format(whois_obj['whois_server'])
            if 'referral_url' in whois_obj and whois_obj['referral_url']:
                result_str += 'Referral URL: {}\n'.format(whois_obj['referral_url'])
            if 'name_servers' in whois_obj and whois_obj['name_servers']:
                result_str += 'Name servers: \n{}\n'.format('\n'.join(['    ' + x.lower() for x in set(whois_obj['name_servers'])]))
            if 'emails' in whois_obj and whois_obj['emails']:
                result_str += 'Emails: \n{}\n'.format('\n'.join(['    ' + x for x in set(whois_obj['emails'])]))
            if 'dnssec' in whois_obj and whois_obj['dnssec']:
                result_str += 'DNSSec: {}\n'.format(whois_obj['dnssec'])
            if 'name' in whois_obj and whois_obj['name']:
                result_str += 'Name: {}\n'.format(whois_obj['name'])
            if 'org' in whois_obj and whois_obj['org']:
                result_str += 'Organization: {}\n'.format(whois_obj['org'])
            if 'address' in whois_obj and whois_obj['address']:
                result_str += 'Address: {}\n'.format(whois_obj['address'])
            if 'city' in whois_obj and whois_obj['city']:
                result_str += 'DNSSec: {}\n'.format(whois_obj['city'])
            if 'state' in whois_obj and whois_obj['state']:
                result_str += 'State: {}\n'.format(whois_obj['state'])
            if 'zipcode' in whois_obj and whois_obj['zipcode']:
                result_str += 'Zipcode: {}\n'.format(whois_obj['zipcode'])
            if 'country' in whois_obj and whois_obj['country']:
                result_str += 'Country: {}\n'.format(whois_obj['country'])

            if result_str:
                db.update_hostnames_description(current_project['id'], form.hostname.data, result_str)

            referer = request.headers.get("Referer")
            referer += '#/hostnames'
            return redirect(referer)

        if form.hostname.data:
            whois_obj = whois.whois(form.hostname.data)
            result_str = ''
            if whois_obj['registrar']:
                result_str += 'Registrar: {}\n'.format(whois_obj['registrar'])
            if whois_obj['whois_server']:
                result_str += 'Whois server: {}\n'.format(whois_obj['whois_server'])
            if whois_obj['referral_url']:
                result_str += 'Referral URL: {}\n'.format(whois_obj['referral_url'])
            if whois_obj['name_servers']:
                result_str += 'Name servers: \n{}\n'.format('\n'.join(['    ' + x.lower() for x in set(whois_obj['name_servers'])]))
            if whois_obj['emails']:
                result_str += 'Emails: \n{}\n'.format('\n'.join(['    ' + x for x in set(whois_obj['emails'])]))
            if whois_obj['dnssec']:
                result_str += 'DNSSec: {}\n'.format(whois_obj['dnssec'])
            if whois_obj['name']:
                result_str += 'Name: {}\n'.format(whois_obj['name'])
            if whois_obj['org']:
                result_str += 'Organization: {}\n'.format(whois_obj['org'])
            if whois_obj['address']:
                result_str += 'Address: {}\n'.format(whois_obj['address'])
            if whois_obj['city']:
                result_str += 'DNSSec: {}\n'.format(whois_obj['city'])
            if whois_obj['state']:
                result_str += 'State: {}\n'.format(whois_obj['state'])
            if whois_obj['zipcode']:
                result_str += 'Zipcode: {}\n'.format(whois_obj['zipcode'])
            if whois_obj['country']:
                result_str += 'Country: {}\n'.format(whois_obj['country'])

            if result_str:
                try:
                    ip = socket.gethostbyname(form.hostname.data)
                    hosts = db.select_ip_from_project(current_project['id'], ip)
                    if not hosts:
                        host_id = db.insert_host(current_project['id'],
                                                 ip,
                                                 current_user['id'],
                                                 'Added from Whois information')
                    else:
                        host_id = hosts[0]['id']

                    hostname_obj = db.select_ip_hostname(host_id, form.hostname.data)
                    if not hostname_obj:
                        hostname_id = db.insert_hostname(host_id, form.hostname.data, '', current_user['id'])
                except:
                    pass

                db.update_hostnames_description(current_project['id'], form.hostname.data, result_str)

        if form.hostnames.data:
            for hostname in form.hostnames.data:
                whois_obj = whois.whois(hostname)
                result_str = ''
                if whois_obj['registrar']:
                    result_str += 'Registrar: {}\n'.format(whois_obj['registrar'])
                if whois_obj['whois_server']:
                    result_str += 'Whois server: {}\n'.format(whois_obj['whois_server'])
                if whois_obj['referral_url']:
                    result_str += 'Referral URL: {}\n'.format(whois_obj['referral_url'])
                if whois_obj['name_servers']:
                    result_str += 'Name servers: \n{}\n'.format('\n'.join(['    ' + x.lower() for x in set(whois_obj['name_servers'])]))
                if whois_obj['emails']:
                    result_str += 'Emails: \n{}\n'.format('\n'.join(['    ' + x for x in set(whois_obj['emails'])]))
                if whois_obj['dnssec']:
                    result_str += 'DNSSec: {}\n'.format(whois_obj['dnssec'])
                if whois_obj['name']:
                    result_str += 'Name: {}\n'.format(whois_obj['name'])
                if whois_obj['org']:
                    result_str += 'Organization: {}\n'.format(whois_obj['org'])
                if whois_obj['address']:
                    result_str += 'Address: {}\n'.format(whois_obj['address'])
                if whois_obj['city']:
                    result_str += 'DNSSec: {}\n'.format(whois_obj['city'])
                if whois_obj['state']:
                    result_str += 'State: {}\n'.format(whois_obj['state'])
                if whois_obj['zipcode']:
                    result_str += 'Zipcode: {}\n'.format(whois_obj['zipcode'])
                if whois_obj['country']:
                    result_str += 'Country: {}\n'.format(whois_obj['country'])

                if result_str:
                    try:
                        ip = socket.gethostbyname(hostname)
                        hosts = db.select_ip_from_project(current_project['id'], ip)
                        if not hosts:
                            host_id = db.insert_host(current_project['id'],
                                                     ip,
                                                     current_user['id'],
                                                     'Added from Whois information')
                        else:
                            host_id = hosts[0]['id']

                        hostname_obj = db.select_ip_hostname(host_id, hostname)
                        if not hostname_obj:
                            hostname_id = db.insert_hostname(host_id, hostname, '', current_user['id'])
                    except:
                        pass

                    db.update_hostnames_description(current_project['id'], hostname, result_str)

    return render_template('project/tools/scanners/whois.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='Whois')
