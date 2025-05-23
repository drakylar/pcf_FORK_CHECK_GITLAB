import ipaddress
from urllib.parse import urlparse

from routes.ui import routes
from functools import wraps
from docxtpl import DocxTemplate, InlineImage, RichText
from docx.shared import Mm
from io import BytesIO
from system.forms import *
from flask import send_from_directory, send_file
import time
import email_validator
from system.crypto_functions import gen_uuid, md5_hex_str, sha1_hex_str, \
    sha256_hex_str, sha512_hex_str, md5_crypt_str, des_crypt_str, \
    sha512_crypt_str, sha256_crypt_str, nt_hex_str, lm_hex_str, rabbitmq_md5_str
from system.security_functions import run_function_timeout, latex_str_escape, sql_to_regexp, extract_to_regexp
from system.report_template_options import group_issues_by, csv_escape, issue_targets_list
from os import path, remove, stat, makedirs, walk
from flask import Response, jsonify
import magic
from flask import escape as htmlspecialchars
import shutil
import calendar
import json, zipfile
import base64
from jinja2.sandbox import SandboxedEnvironment
from IPy import IP
import urllib
import re

from app import check_session, db, session, render_template, redirect, request, \
    config, send_log_data, requires_authorization, cache


def check_project_access(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        project_id = kwargs['project_id']
        current_project = db.check_user_project_access(str(project_id),
                                                       session['id'])
        if not current_project:
            return redirect('/projects/')
        kwargs['current_project'] = current_project
        return fn(*args, **kwargs)

    return decorated_view


def check_issue_template_access(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        template_id = str(kwargs['template_id'])
        current_user = kwargs['current_user']
        current_project = kwargs['current_project']
        current_template = db.check_user_issue_template_access(template_id, current_user['id'], current_user['email'])
        if not current_template:
            return redirect('/project/{}/issues'.format(current_project['id']))
        kwargs['current_template'] = current_template[0]
        return fn(*args, **kwargs)

    return decorated_view


def check_note_access(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        note_id = str(kwargs['note_id'])
        current_user = kwargs['current_user']
        current_project = kwargs['current_project']
        current_note = db.select_project_note(current_project['id'], note_id)
        if not current_note:
            return redirect('/project/{}/notes'.format(current_project['id']))
        kwargs['current_note'] = current_note[0]
        return fn(*args, **kwargs)

    return decorated_view


def check_chat_access(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        current_project = kwargs['current_project']
        chat_id = kwargs['chat_id']
        current_chat = db.select_project_chat(current_project['id'],
                                              str(chat_id))
        if not current_chat:
            return redirect('/projects/')
        kwargs['current_chat'] = current_chat[0]
        return fn(*args, **kwargs)

    return decorated_view


def check_project_archived(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        current_project = kwargs['current_project']

        if current_project['status'] == 0 or (current_project[
                                                  'end_date'] < time.time() and
                                              current_project[
                                                  'auto_archive'] == 1):
            if current_project['status'] == 1:
                db.update_project_status(current_project['id'], 0)
            return redirect('/projects/')
        return fn(*args, **kwargs)

    return decorated_view


def check_project_issue(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        current_project = kwargs['current_project']
        issue_id = str(kwargs['issue_id'])
        current_issue = db.select_issue(str(issue_id))
        if not current_issue:
            return redirect(
                '/project/{}/issues/'.format(current_project['id']))
        current_issue = current_issue[0]
        if current_issue['project_id'] != current_project['id']:
            return redirect(
                '/project/{}/issues/'.format(current_project['id']))
        kwargs['current_issue'] = current_issue
        return fn(*args, **kwargs)

    return decorated_view


def check_project_creds(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        current_project = kwargs['current_project']
        creds_id = str(kwargs['creds_id'])
        current_creds = db.select_creds(str(creds_id))
        if not current_creds:
            return redirect(
                '/project/{}/credentials/'.format(current_project['id']))
        current_creds = current_creds[0]
        if current_creds['project_id'] != current_project['id']:
            return redirect(
                '/project/{}/credentials/'.format(current_project['id']))
        kwargs['current_creds'] = current_creds
        return fn(*args, **kwargs)

    return decorated_view


def check_project_network(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        current_project = kwargs['current_project']
        network_id = str(kwargs['network_id'])
        current_network = db.select_project_networks_by_id(current_project['id'], str(network_id))
        if not current_network:
            return redirect(
                '/project/{}/networks/'.format(current_project['id']))
        current_network = current_network[0]
        kwargs['current_network'] = current_network
        return fn(*args, **kwargs)

    return decorated_view


def check_project_file_access(fn):
    @wraps(fn)
    def decorated_view(*args, **kwargs):
        project_id = str(kwargs['project_id'])
        file_id = str(kwargs['file_id'])
        current_file = db.select_files(file_id)
        if not current_file:
            return redirect('/project/{}/files/'.format(project_id))
        current_file = current_file[0]
        if current_file['project_id'] != project_id:
            return redirect('/project/')
        kwargs['current_file'] = current_file
        return fn(*args, **kwargs)

    return decorated_view


@cache.cached(timeout=120)
@routes.route('/static/files/fields/<uuid:file_id>')
def getFieldFile(file_id):
    return send_from_directory('static/files/fields', str(file_id),
                               as_attachment=True,
                               attachment_filename=
                               db.select_files(str(file_id))[0]['filename'])


@routes.route('/project/<uuid:project_id>/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_index(project_id, current_project, current_user):
    # get project users & teams

    user_ids = db.select_project_users(current_project['id'])

    user_json = {x['id']: {'email': htmlspecialchars(x['email']), 'fname': htmlspecialchars(x['fname']),
                           'lname': htmlspecialchars(x['lname'])} for x in user_ids}

    team_json = {}

    for team_id in json.loads(current_project['teams']):
        current_team = db.select_team_by_id(team_id)[0]
        team_json[current_team['id']] = htmlspecialchars(current_team['name'])

    return render_template('project/stats/stats.html',
                           current_project=current_project,
                           tab_name='Stats',
                           project_users=user_json,
                           project_teams=team_json,
                           current_time=time.time())


@routes.route('/project/<uuid:project_id>/hosts/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def hosts(project_id, current_project, current_user):
    return render_template('project/hosts/list.html',
                           current_project=current_project,
                           tab_name='Hosts')


@routes.route('/project/<uuid:project_id>/hosts/new_host', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_host(project_id, current_project, current_user):
    return render_template('project/hosts/new.html',
                           current_project=current_project,
                           tab_name='Add host')


@routes.route('/project/<uuid:project_id>/hosts/new_host', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_host_form(project_id, current_project, current_user):
    form = NewHost()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if not errors and db.select_ip_from_project(
            project_id=current_project['id'], ip=form.ip.data):
        errors.append('IP already in project!')

    if errors:
        return render_template('project/hosts/new.html',
                               current_project=current_project,
                               errors=errors,
                               tab_name='Add host')
    ip_id = db.insert_host(current_project['id'],
                           form.ip.data,
                           session['id'],
                           form.description.data)

    return redirect('/project/{}/hosts/'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/host/<uuid:host_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def host_page(project_id, host_id, current_project, current_user):
    current_host = db.select_project_host(current_project['id'], str(host_id))
    if not current_host:
        return redirect('/project/{}/hosts/'.format(current_project['id']))
    current_host = current_host[0]
    return render_template('project/hosts/host.html',
                           current_project=current_project,
                           current_host=current_host,
                           tab_name=current_host['ip'])


@routes.route('/project/<uuid:project_id>/host/<uuid:host_id>/',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def host_page_form(project_id, host_id, current_project, current_user):
    current_host = db.select_project_host(current_project['id'], str(host_id))
    if not current_host:
        return redirect('/project/{}/hosts/'.format(current_project['id']))
    current_host = current_host[0]

    if 'delete_host_issue' in request.form:
        form = DeleteHostIssue()
        form.validate()
        errors = []
        if form.errors:
            for field in form.errors:
                errors += form.errors[field]
        if not errors:
            current_issue = db.select_issue(form.issue_id.data)
            if not current_issue:
                errors.append('Issue not found!')
            elif current_issue[0]['project_id'] != current_project['id']:
                errors.append('Issue is in another project!')
            else:
                db.delete_issue_host(current_issue[0]['id'], current_host['id'])

    if 'delete_port' in request.form:
        form = DeletePort()
        form.validate()
        errors = []
        if form.errors:
            for field in form.errors:
                errors += form.errors[field]
        if not errors:
            current_port = db.select_port(form.port_id.data)
            if not current_port:
                errors.append('Port not found!')
            elif current_port[0]['host_id'] != current_host['id']:
                errors.append('Port is in another host!')
            else:
                db.delete_port_safe(current_port[0]['id'])

    if 'update_description' in request.form:
        if 'Submit' in request.form and request.form['Submit'] == 'Delete':
            ports = db.select_host_ports(current_host['id'], full=True)
            for current_port in ports:
                db.delete_port_safe(current_port['id'])
            db.delete_host(current_host['id'])
            return redirect('/project/{}/hosts/'.format(current_project['id']))

        form = UpdateHostDescription()
        form.validate()
        errors = []
        if form.errors:
            for field in form.errors:
                errors += form.errors[field]

        if not errors:
            os = form.os_input.data
            if form.os.data:
                os = form.os.data
            db.update_host_comment_threats(current_host['id'],
                                           form.comment.data,
                                           form.threats.data,
                                           os)
            current_host = \
                db.select_project_host(current_project['id'], str(host_id))[0]

        return render_template('project/hosts/host.html',
                               current_project=current_project,
                               current_host=current_host,
                               edit_description_errors=errors,
                               tab_name=current_host['ip'])

    if 'add_port' in request.form:
        form = AddPort()
        form.validate()
        errors = []
        if form.errors:
            for field in form.errors:
                errors += form.errors[field]

        # check port number
        port_type = 'tcp'  # 1 - tcp, 2 - udp
        if form.port.data.endswith('/udp'):
            port_type = 'udp'
        try:
            port_num = int(form.port.data.replace('/' + port_type, ''))
            if (port_num < 1) or (port_num > 65535):
                errors.append('Port number is invalid {1..65535}')
        except ValueError:
            errors.append('Port number has invalid format')

        if not errors:
            ports = db.select_host_ports(current_host['id'])
            service = form.service_text.data if form.service_text.data else form.service.data
            found = {}
            for port in ports:
                if int(port['port']) == port_num and port['is_tcp'] == (
                        port_type == 'tcp'):
                    found = port
            if not found:
                db.insert_host_port(current_host['id'],
                                    port_num,
                                    port_type == 'tcp',
                                    service,
                                    form.description.data,
                                    session['id'],
                                    current_project['id'])
            else:
                db.update_port_proto_description(found['id'],
                                                 service,
                                                 form.description.data)

        return render_template('project/hosts/host.html',
                               current_project=current_project,
                               current_host=current_host,
                               add_port_errors=errors,
                               tab_name=current_host['ip'])

    if 'add_hostname' in request.form:
        form = AddHostname()
        form.validate()
        errors = []
        if form.errors:
            for field in form.errors:
                errors += form.errors[field]

        # validate hostname
        if not errors:
            try:
                email_validator.validate_email_domain_part(form.hostname.data)
            except email_validator.EmailNotValidError:
                errors.append('Hostname not valid!')

        if not errors:
            hostnames = db.find_ip_hostname(current_host['id'],
                                            form.hostname.data)
            if hostnames:
                db.update_hostname(hostnames[0]['id'], form.comment.data)
            else:
                hostname_id = db.insert_hostname(current_host['id'],
                                                 form.hostname.data,
                                                 form.comment.data,
                                                 session['id'])

        return render_template('project/hosts/host.html',
                               current_project=current_project,
                               current_host=current_host,
                               add_hostname_errors=errors,
                               tab_name=current_host['ip'])

    if 'delete_hostname' in request.form:
        form = DeleteHostname()
        form.validate()
        errors = []
        if form.errors:
            for field in form.errors:
                errors += form.errors[field]

        if not errors:
            found = db.check_host_hostname_id(current_host['id'],
                                              form.hostname_id.data)
            if not found:
                errors.append('Hostname ID in this host not found!')

        if not errors:
            db.delete_hostname_safe(form.hostname_id.data)

        return render_template('project/hosts/host.html',
                               current_project=current_project,
                               current_host=current_host,
                               delete_hostname_errors=errors,
                               tab_name=current_host['ip'])

    return render_template('project/hosts/host.html',
                           current_project=current_project,
                           current_host=current_host,
                           tab_name=current_host['ip'])


@routes.route('/project/<uuid:project_id>/hosts/multiple_delete',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def multiple_host_delete(project_id, current_project, current_user):
    form = MultipleDeleteHosts()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if not errors:
        for host_id in form.host.data:
            db.delete_host_safe(current_project['id'], host_id)
    return 'ok'


@routes.route('/project/<uuid:project_id>/new_issue', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_issue(project_id, current_project, current_user):
    issues_list = [x['name'] for x in db.select_project_issues(current_project['id'])]
    return render_template('project/issues/new.html',
                           current_project=current_project,
                           issues_list=issues_list,
                           tab_name='New issue')


@routes.route('/project/<uuid:project_id>/new_issue', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_issue_form(project_id, current_project, current_user):
    issues_list = [x['name'] for x in db.select_project_issues(current_project['id'])]

    form = NewIssue()
    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    services = {}

    # check port_id variable
    if not errors:
        for port_id in form.ip_port.data:
            if not db.check_port_in_project(current_project['id'], port_id):
                errors.append('Some ports are not in project!')
            else:
                if port_id in services:
                    if "0" not in services[port_id]:
                        services[port_id].append("0")
                else:
                    services[port_id] = ["0"]

    # check host_id variable
    if not errors:
        for host_port in form.host_port.data:
            port_id = host_port.split(':')[0]
            hostname_id = host_port.split(':')[1]
            port_data = db.select_port(port_id)
            hostname_data = db.select_hostname(hostname_id)
            if not port_data or not hostname_data:
                errors.append('Hostname not found error!')
            else:
                if port_data[0]['host_id'] != hostname_data[0]['host_id']:
                    errors.append('Some ports are not with these hostnames.')
                else:
                    if port_id not in services:
                        services[port_id] = [hostname_id]
                    else:
                        if hostname_id not in services[port_id]:
                            services[port_id].append(hostname_id)

    file_move_list = []
    if not errors:
        # collecting additional fields
        field_counter = 0
        add_fields_dict = {}
        if len(form.additional_field_name.data) == \
                len(form.additional_field_type.data) == \
                len(form.additional_field_value.data):
            for field_name in form.additional_field_name.data:
                field_type = form.additional_field_type.data[field_counter]
                field_value = form.additional_field_value.data[field_counter]
                if field_type in ["text", "number", "float", "boolean"]:
                    # add text field
                    try:
                        if field_type == "text":
                            type_func = str
                        elif field_type == "number":
                            type_func = int
                        elif field_type == "float":
                            type_func = float
                        elif field_type == "boolean":
                            type_func = lambda x: bool(int(x))
                        add_fields_dict[field_name] = {
                            'val': type_func(field_value),
                            'type': field_type
                        }
                    except:
                        pass

                field_counter += 1
        if len(form.additional_field_file.data) == len(form.additional_field_filename.data):
            file_counter = 0
            for file_field_name in form.additional_field_filename.data:
                file = form.additional_field_file.data[file_counter]
                filename = file.filename
                field_id = gen_uuid()
                tmp_file_path = path.join(config['main']['tmp_path'], field_id)
                file.save(tmp_file_path)
                file.close()
                file_size = stat(tmp_file_path).st_size

                if file_size > int(config['files']['poc_max_size']):
                    errors.append('File too large!')
                    remove(tmp_file_path)
                else:
                    file_path = path.join('./static/files/fields/', field_id)
                    file_move_list.append([tmp_file_path, file_path, field_id, filename])
                    add_fields_dict[file_field_name] = {}
                    add_fields_dict[file_field_name]['type'] = 'file'
                    add_fields_dict[file_field_name]['val'] = field_id
                file_counter += 1

    if not errors:
        cvss = form.cvss.data
        criticality = form.criticality.data
        if 0 <= criticality <= 10:
            cvss = criticality

        issue_id = db.insert_new_issue(form.name.data, form.description.data,
                                       form.url.data,
                                       cvss, session['id'], services,
                                       form.status.data, current_project['id'],
                                       form.cve.data,
                                       issue_type=form.issue_type.data,
                                       fix=form.fix.data,
                                       param=form.param.data,
                                       fields=add_fields_dict,
                                       technical=form.technical.data,
                                       risks=form.risks.data,
                                       references=form.references.data,
                                       intruder=form.intruder.data)
        for file_obj in file_move_list:
            shutil.move(file_obj[0], file_obj[1])

            file_data = b''
            if config["files"]["files_storage"] == 'database':
                f = open(file_obj[1], 'rb')
                file_data = f.read()
                f.close()
                remove(file_obj[1])

            db.insert_new_file(file_obj[2], current_project['id'],
                               file_obj[3], '', {}, 'field', current_user['id'],
                               storage=config["files"]["files_storage"],
                               data=file_data)
        return redirect(
            '/project/{}/issue/{}/'.format(current_project['id'], issue_id))
    else:
        # delete files fields
        for file_obj in file_move_list:
            try:
                remove(file_obj[0])
            except:
                pass

    return render_template('project/issues/new.html',
                           current_project=current_project,
                           errors=errors,
                           issues_list=issues_list,
                           tab_name='New issue')


@routes.route('/project/<uuid:project_id>/issues/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def issues_list(project_id, current_project, current_user):
    return render_template('project/issues/list.html',
                           current_project=current_project,
                           tab_name='Issues',
                           current_user=current_user)


@routes.route('/project/<uuid:project_id>/issues/multiple_delete', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def multiple_issue_delete(project_id, current_project, current_user):
    form = MultipleDeleteIssues()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if not errors:
        for issue_id in form.issue.data:
            db.delete_issue_safe(current_project['id'], issue_id)
    return 'ok'


@routes.route('/project/<uuid:project_id>/issues/join_issues', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def join_issues(project_id, current_project, current_user):
    form = JoinIssues()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if not errors:
        issues_list = [str(x) for x in form.issue.data]
        if issues_list:
            db.join_duplicate_issues(current_project['id'], issues_list)
    return 'ok'


@routes.route('/project/<uuid:project_id>/issues/multiple_edit', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def multiple_issue_edit(project_id, current_project, current_user):
    form = MultipleEditIssues()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if not errors:
        for issue_id in form.issue.data:
            issue_obj = db.select_issue(issue_id)
            if issue_obj and issue_obj[0]['project_id'] == current_project['id']:
                if form.criticality.data != -1 and form.criticality.data >= 0:
                    db.update_issue_cvss(issue_id, form.criticality.data)
                if form.status.data != "-1":
                    db.update_issue_status(issue_id, form.status.data)
    return 'ok'


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_issue
@send_log_data
def issues_info(project_id, issue_id, current_project, current_user,
                current_issue):
    return render_template('project/issues/edit.html',
                           current_project=current_project,
                           current_issue=current_issue,
                           tab_name=current_issue['name'] if current_issue['name'] else 'Issue',
                           current_user=current_user)


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/template/<uuid:template_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_issue
@check_issue_template_access
@send_log_data
def edit_issue_with_template(project_id, issue_id, template_id, current_project, current_user,
                             current_issue, current_template):
    return render_template('project/issues/with_template.html',
                           current_project=current_project,
                           current_issue=current_issue,
                           tab_name=current_issue['name'] if current_issue['name'] else 'Issue',
                           current_user=current_user,
                           current_template=current_template)


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/template/<uuid:template_id>/',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_issue
@check_issue_template_access
@check_project_archived
@send_log_data
def edit_issue_with_template_form(project_id, issue_id, template_id, current_project, current_user,
                                  current_issue, current_template):
    form = EditIssueFromTemplate()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not (len(form.variable_value.data) == len(form.variable_type.data) == len(form.variable_name.data)):
        errors.append('Error with variables form!')

    if not errors:
        # add variables
        variables_counter = 0
        add_variables_dict = {}
        for variable_name in form.variable_name.data:
            variable_type = form.variable_type.data[variables_counter]
            variable_value = form.variable_value.data[variables_counter]
            if variable_type in ["text", "number", "float", "boolean"]:
                # add text field
                try:
                    if variable_type == "text":
                        type_func = str
                    elif variable_type == "number":
                        type_func = int
                    elif variable_type == "float":
                        type_func = float
                    elif variable_type == "boolean":
                        type_func = lambda x: bool(int(x))

                    add_variables_dict[variable_name] = {
                        'val': type_func(variable_value) if variable_type == 'text' or variable_value else type_func(0),
                        'type': variable_type
                    }
                except:
                    pass
                variables_counter += 1

        def replace_tpl_text(text: str):
            for variable_name in add_variables_dict:
                variable_type = add_variables_dict[variable_name]['type']
                variable_value = add_variables_dict[variable_name]['val']
                if variable_type == 'boolean':
                    variable_value = int(variable_value)
                text = text.replace('__' + variable_name + '__', str(variable_value))
            return text

        issue_name = replace_tpl_text(current_template['name'])
        issue_description = replace_tpl_text(current_template['description'])
        issue_url_path = replace_tpl_text(current_template['url_path'])
        issue_cvss = current_template['cvss']
        issue_cwe = current_template['cwe']
        issue_cve = replace_tpl_text(current_template['cve'])
        issue_status = replace_tpl_text(current_template['status'])
        issue_type = replace_tpl_text(current_template['type'])
        issue_fix = replace_tpl_text(current_template['fix'])
        issue_param = replace_tpl_text(current_template['param'])
        issue_technical = replace_tpl_text(current_template['technical'])
        issue_risks = replace_tpl_text(current_template['risks'])
        issue_references = replace_tpl_text(current_template['references'])
        issue_intruder = replace_tpl_text(current_template['intruder'])

        issue_fields = json.loads(current_template['fields'])
        old_issue_fields = json.loads(current_issue['fields'])

        for field_name in issue_fields:
            if issue_fields[field_name]['type'] == 'text':
                issue_fields[field_name]['val'] = replace_tpl_text(issue_fields[field_name]['val'])

        for old_field_name in old_issue_fields:
            if old_field_name not in issue_fields:
                issue_fields[old_field_name] = old_issue_fields[old_field_name]

        services = json.loads(current_issue['services'])

        issue_fields["pcf_last_used_template"] = {
            "type": "text",
            "val": current_template['id']
        }

        db.update_issue_fields(current_issue['id'], issue_fields)
        db.update_issue(current_issue['id'], issue_name,
                        issue_description, issue_url_path,
                        issue_cvss, services, issue_status,
                        issue_cve, issue_cwe, issue_fix,
                        issue_type, issue_param, issue_technical, issue_risks,
                        issue_references, issue_intruder)

        return redirect('/project/{}/issue/{}/'.format(current_project['id'], current_issue['id']))

    return render_template('project/issues/with_template.html',
                           current_project=current_project,
                           current_issue=current_issue,
                           tab_name=current_issue['name'] if current_issue['name'] else 'Issue',
                           current_user=current_user,
                           current_template=current_template)


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/hosts_ports_list',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_issue
@send_log_data
def filter_host_port_form(project_id, issue_id, current_project, current_user,
                          current_issue):
    ports_list = db.select_project_pair_host_port(current_project['id'])
    issue_service_dict = json.loads(current_issue['services'])

    # get ports ips

    result = {}
    for port in ports_list:
        port['checked'] = False
        if port['port_id'] in issue_service_dict and "0" in issue_service_dict[port['port_id']]:
            port['checked'] = True

    result['ips'] = ports_list

    # get ports hostnames
    hostnames_list = db.select_project_pair_hostname_port(current_project['id'])
    for port in hostnames_list:
        port['checked'] = False
        if port['port_id'] in issue_service_dict and port['hostname_id'] in issue_service_dict[port['port_id']]:
            port['checked'] = True
    result['hostnames'] = hostnames_list

    return json.dumps(result)


@routes.route('/project/<uuid:project_id>/issues/hosts_ports_list',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def filter_host_port_issues(project_id, current_project, current_user):
    ports_list = db.select_project_pair_host_port(current_project['id'])

    # get ports ips
    result = {}
    result['ips'] = ports_list

    # get ports hostnames
    hostnames_list = db.select_project_pair_hostname_port(current_project['id'])
    result['hostnames'] = hostnames_list

    return json.dumps(result)


@routes.route('/project/<uuid:project_id>/issues/hosts_hostnames_list',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def hosts_hostnames_list(project_id, current_project, current_user):
    hosts_hostnames = db.select_project_hosts_hostnames(current_project['id'])

    return json.dumps(hosts_hostnames)


@routes.route('/project/<uuid:project_id>/issues/networks_list',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def networks_list(project_id, current_project, current_user):
    hosts_hostnames = [{'id': x['id'], 'network': '{}/{}'.format(x['ip'], x['mask'])} for x in
                       db.select_project_networks(current_project['id'])]
    return json.dumps(hosts_hostnames)


@routes.route('/project/<uuid:project_id>/issues/hosts_list',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def hosts_list(project_id, current_project, current_user):
    hosts = [{'id': x['id'], 'ip': x['ip']} for x in db.select_project_hosts(current_project['id'])]
    return json.dumps(hosts)


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def issues_info_form(project_id, issue_id, current_project, current_user,
                     current_issue):
    form = UpdateIssue()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    services = {}

    # check port_id variable
    if not errors:
        for port_id in form.ip_port.data:
            if not db.check_port_in_project(current_project['id'], port_id):
                errors.append('Some ports are not in project!')
            else:
                if port_id in services:
                    if "0" not in services[port_id]:
                        services[port_id].append("0")
                else:
                    services[port_id] = ["0"]

    # check host_id variable
    if not errors:
        for host_port in form.host_port.data:
            port_id = host_port.split(':')[0]
            hostname_id = host_port.split(':')[1]
            port_data = db.select_port(port_id)
            hostname_data = db.select_hostname(hostname_id)
            if not port_data or not hostname_data:
                errors.append('Hostname not found error!')
            else:
                if port_data[0]['host_id'] != hostname_data[0]['host_id']:
                    errors.append('Some ports are not with these hostnames.')
                else:
                    if port_id not in services:
                        services[port_id] = [hostname_id]
                    else:
                        if hostname_id not in services[port_id]:
                            services[port_id].append(hostname_id)

    cvss = form.cvss.data
    criticality = form.criticality.data
    if criticality >= 0 and criticality <= 10:
        cvss = criticality

    if not errors:
        db.update_issue(current_issue['id'], form.name.data,
                        form.description.data, form.url.data,
                        cvss, services, form.status.data,
                        form.cve.data, form.cwe.data,
                        issue_type=form.issue_type.data,
                        fix=form.fix.data,
                        param=form.param.data,
                        technical=form.technical.data,
                        risks=form.risks.data,
                        references=form.references.data,
                        intruder=form.intruder.data)

    current_issue = db.select_issue(str(issue_id))[0]

    return render_template('project/issues/edit.html',
                           current_project=current_project,
                           current_issue=current_issue,
                           update_info_errors=errors,
                           tab_name=current_issue['name'] if current_issue['name'] else 'Issue',
                           current_user=current_user)


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/edit_text_fields',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def issues_edit_fields(project_id, issue_id, current_project, current_user,
                       current_issue):
    form = EditIssueFields()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        field_counter = 0
        add_fields_dict = {}

        old_field_dict = json.loads(current_issue['fields'])

        # check old text fields
        for field_name in old_field_dict:
            field_type = old_field_dict[field_name]['type']
            field_value = old_field_dict[field_name]['val']
            if field_type == 'file':
                add_fields_dict[field_name] = {
                    'type': field_type,
                    'val': field_value
                }

        if len(form.additional_field_name.data) == \
                len(form.additional_field_type.data) == \
                len(form.additional_field_value.data):
            for field_name in form.additional_field_name.data:
                field_type = form.additional_field_type.data[field_counter]
                field_value = form.additional_field_value.data[field_counter]
                if field_type in ["text", "number", "float", "boolean"]:
                    # add text field
                    try:
                        if field_type == "text":
                            type_func = str
                        elif field_type == "number":
                            type_func = int
                        elif field_type == "float":
                            type_func = float
                        elif field_type == "boolean":
                            type_func = lambda x: bool(int(x))
                        add_fields_dict[field_name] = {
                            'val': type_func(field_value),
                            'type': field_type
                        }
                    except:
                        pass

                field_counter += 1

        db.update_issue_text_fields(current_issue['id'], add_fields_dict)
    return redirect('/project/{}/issue/{}/#/fields'.format(current_project['id'],
                                                           current_issue['id']))


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/edit_file_fields',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def issues_edit_file_fields(project_id, issue_id, current_project, current_user,
                            current_issue):
    form = EditIssueFiles()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        add_fields_dict = {}

        old_field_dict = json.loads(current_issue['fields'])

        old_files_list = form.additional_field_old_file.data

        # check old text fields
        for field_name in old_field_dict:
            field_type = old_field_dict[field_name]['type']
            field_value = old_field_dict[field_name]['val']
            if field_type != 'file' or field_name in old_files_list:
                add_fields_dict[field_name] = {
                    'type': field_type,
                    'val': field_value
                }
            elif field_type == 'file':
                if field_name not in old_files_list:
                    # delete file if not exists in old file list
                    file_uuid = field_value
                    path_file = path.join('./static/files/fields/', file_uuid)
                    remove(path_file)
                    db.delete_file(file_uuid)

        # add new fields
        if len(form.additional_field_name.data) == \
                len(form.additional_field_file.data):
            for field_name, field_file in zip(form.additional_field_name.data,
                                              form.additional_field_file.data):
                filename = field_file.filename
                field_id = gen_uuid()
                tmp_file_path = path.join(config['main']['tmp_path'], field_id)
                field_file.save(tmp_file_path)
                field_file.close()
                file_size = stat(tmp_file_path).st_size

                if file_size > int(config['files']['poc_max_size']):
                    errors.append('File too large!')
                    remove(tmp_file_path)
                else:
                    file_path = path.join('./static/files/fields/', field_id)
                    shutil.move(tmp_file_path, file_path)
                    add_fields_dict[field_name] = {}
                    add_fields_dict[field_name]['type'] = 'file'
                    add_fields_dict[field_name]['val'] = field_id

                    file_data = b''
                    if config["files"]["poc_storage"] == 'database':
                        f = open(file_path, 'rb')
                        file_data = f.read()
                        f.close()
                        remove(file_path)

                    db.insert_new_file(field_id, current_project['id'],
                                       filename, '', {}, 'field', current_user['id'],
                                       storage=config["files"]["poc_storage"],
                                       data=file_data)
        db.update_issue_fields(current_issue['id'], add_fields_dict)

    return redirect('/project/{}/issue/{}/#/fields'.format(current_project['id'],
                                                           current_issue['id']))


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/delete_issue',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def delete_issue_form(project_id, issue_id, current_project, current_user,
                      current_issue):
    db.delete_issue_safe(current_project['id'], current_issue['id'])
    return redirect('/project/{}/issues/'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/new_poc',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def new_poc_form(project_id, issue_id, current_project, current_user,
                 current_issue):
    form = NewPOC()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        port_id = form.service.data.split(':')[0]
        hostname_id = form.service.data.split(':')[1]
        if not (port_id == '0' and hostname_id == '0'):
            # check if port-host in issue
            if not db.check_hostname_port_in_issue(hostname_id, port_id,
                                                   current_issue['id']):
                errors.append('Hostname-port id pair is not in this issue!')

    # save template file
    if not errors:
        file_type = 'image'
        file = request.files.get('file')
        poc_id = gen_uuid()
        tmp_file_path = path.join(config['main']['tmp_path'], poc_id)
        file.save(tmp_file_path)
        file.close()
        file_size = stat(tmp_file_path).st_size
        if file_size > int(config['files']['poc_max_size']):
            errors.append("File too large!")
            remove(tmp_file_path)

    if not errors:
        # check file type
        magic_obj = magic.Magic(mime=True)
        magic_type = magic_obj.from_file(tmp_file_path).lower()
        print(magic_type)
        if 'text' in magic_type:
            file_type = 'text'
        elif 'image' in magic_type:
            file_type = 'image'
        elif '/pdf' in magic_type:
            file_type = 'document'
        elif 'officedocument' in magic_type or 'word' in magic_type or 'msword' in magic_type:
            file_type = 'document'
        else:
            errors.append('Unknown file format {}'.format(file_type))
            remove(tmp_file_path)
            return render_template('project/issues/edit.html',
                                   current_project=current_project,
                                   current_issue=current_issue,
                                   add_poc_error=errors,
                                   tab_name=current_issue['name'] if current_issue['name'] else 'Issue')
        # move file to new dir
        new_file_path = path.join('./static/files/poc/', poc_id)
        shutil.move(tmp_file_path, new_file_path)

        file_data = b''

        if config['files']['poc_storage'] == 'database':
            f = open(new_file_path, 'rb')
            file_data = f.read()
            f.close()
            remove(new_file_path)

        db.insert_new_poc(port_id,
                          form.comment.data,
                          file_type,
                          file.filename,
                          current_issue['id'],
                          current_user['id'],
                          hostname_id,
                          poc_id,
                          storage=config['files']['poc_storage'],
                          data=file_data)
        return redirect('/project/{}/issue/{}/'.format(current_project['id'],
                                                       current_issue['id']))

    return render_template('project/issues/edit.html',
                           current_project=current_project,
                           current_issue=current_issue,
                           poc_errors=errors,
                           tab_name=current_issue['name'] if current_issue['name'] else 'Issue')


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/delete_poc',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def delete_poc_form(project_id, issue_id, current_project, current_user, current_issue):
    form = DeletePOC()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        current_poc = db.select_poc(form.poc_id.data)
        if not current_poc:
            errors.append('Poc-ID does not exist!')
        elif current_poc[0]['issue_id'] != current_issue['id']:
            errors.append('PoC is not in this issue!')
        else:
            current_poc = current_poc[0]
            db.delete_poc(current_poc['id'])
            return redirect(
                '/project/{}/issue/{}/#/poc'.format(current_project['id'],
                                                    current_issue['id']))

    return render_template('project/issues/edit.html',
                           current_project=current_project,
                           current_issue=current_issue,
                           poc_errors=errors,
                           tab_name=current_issue['name'] if current_issue['name'] else 'Issue')


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/edit_poc',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def edit_poc_form(project_id, issue_id, current_project, current_user, current_issue):
    form = EditPOC()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        port_id = form.service.data.split(':')[0]
        hostname_id = form.service.data.split(':')[1]
        if not (port_id == '0' and hostname_id == '0'):
            # check if port-host in issue
            if not db.check_hostname_port_in_issue(hostname_id, port_id,
                                                   current_issue['id']):
                errors.append('Hostname-port id pair is not in this issue!')

    if not errors:
        current_poc = db.select_poc(form.poc_id.data)
        if not current_poc:
            errors.append('Poc-ID does not exist!')
        elif current_poc[0]['issue_id'] != current_issue['id']:
            errors.append('PoC is not in this issue!')
        else:
            current_poc = current_poc[0]
            db.update_poc_info(current_poc['id'], port_id, hostname_id, form.comment.data, current_issue['id'])
            return {"status": "ok"}
    return {"status": "error", "errors": errors}


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/edit_field', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def edit_issie_field(project_id, issue_id, current_project, current_user, current_issue):
    form = EditIssueField()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        # bad code, need to edit later
        # if cvss
        if form.additional_field_name.data == 'origin_cvss':
            db.update_issue_cvss(current_issue['id'], form.additional_field_value.data)
            return 'ok'
        else:
            db.update_issue_field(
                current_issue['id'],
                form.additional_field_name.data,
                form.additional_field_type.data,
                form.additional_field_value.data
            )
            return 'ok'

    return 'error'


@routes.route('/project/<uuid:project_id>/issue/<uuid:issue_id>/set_priority',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_issue
@send_log_data
def set_poc_priority(project_id, issue_id, current_project, current_user,
                     current_issue):
    form = SetPoCPriority()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        current_poc = db.select_poc(form.poc_id.data)
        if not current_poc:
            errors.append('Poc-ID does not exist!')
        elif current_poc[0]['issue_id'] != current_issue['id']:
            errors.append('PoC is not in this issue!')
        else:
            current_poc = current_poc[0]
            db.update_poc_priority(current_poc['id'], form.priority.data)
    return 'ok'


@routes.route('/project/<uuid:project_id>/networks/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def networks(project_id, current_project, current_user):
    return render_template('project/networks/list.html',
                           current_project=current_project,
                           tab_name='Networks')


@routes.route('/project/<uuid:project_id>/networks/graph',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def networks_graph(project_id, current_project, current_user):
    return render_template('project/networks/graph.html',
                           current_project=current_project,
                           tab_name='Networks graph')


@routes.route('/project/<uuid:project_id>/networks/graph.json',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def networks_graph_json(project_id, current_project, current_user):
    j = []
    # add nodes
    hosts = db.select_project_hosts(current_project['id'])

    networks = db.select_project_networks(current_project['id'])
    paths = db.select_project_paths(current_project['id'])
    for current_network in networks:
        j.append({
            'group': 'nodes',
            'data': {
                'id': 'network_' + current_network['id'],
                'name': '{} ({}/{})'.format(current_network['name'], current_network['ip'], current_network['mask'])
            }
        })
        current_network['ip_obj'] = ipaddress.ip_network('{}/{}'.format(current_network['ip'], current_network['mask']),
                                                         False)

    j.append({
        'group': 'nodes',
        'data': {
            'id': 'network_0',
            'name': '0.0.0.0/0'
        }
    })

    for current_host in hosts:

        os_image = 'server.png'
        if 'win' in current_host['os'].lower():
            os_image = 'windows.png'
        elif 'mac' in current_host['os'].lower():
            os_image = 'macos.png'
        elif 'lin' in current_host['os'].lower():
            os_image = 'linux.png'

        ip_obj = ipaddress.ip_address(current_host['ip'])

        ip_json = {
            'group': 'nodes',
            'data': {
                'id': 'host_' + current_host['id'],
                'name': current_host['ip'],
                'image': '/static/images/' + os_image,
                'threats': json.loads(current_host['threats'])
            }
        }
        found = 0
        for current_network in networks:
            if ip_obj in current_network['ip_obj']:
                ip_json['data']['parent'] = 'network_' + current_network['id']
                found = 1
        if not found:
            ip_json['data']['parent'] = 'network_0'
        j.append(ip_json)

    # j = j[::-1]

    for current_path in paths:
        source_id = ''
        destination_id = ''

        if current_path['host_out']:
            source_id = 'host_' + current_path['host_out']
        else:
            source_id = 'network_' + current_path['network_out']

        if current_path['host_in']:
            destination_id = 'host_' + current_path['host_in']
        else:
            destination_id = 'network_' + current_path['network_in']

        j.append({
            'group': 'edges',
            'data': {
                'id': 'path_' + current_path['id'],
                'source': source_id,
                'target': destination_id,
                'type': current_path['type'],
                'direction': current_path['direction']
            }
        })

    return json.dumps(j)


@routes.route('/project/<uuid:project_id>/networks/new_network',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_network(project_id, current_project, current_user):
    return render_template('project/networks/new.html',
                           current_project=current_project,
                           tab_name='New network')


@routes.route('/project/<uuid:project_id>/networks/new_network',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_network_form(project_id, current_project, current_user):
    form = NewNetwork()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    is_ipv6 = False

    if not errors:
        is_ipv6 = ':' in form.ip.data

    if form.mask.data > 32 and not is_ipv6:
        errors.append('Mask too large for ipv4')
    if form.mask.data > 128 and is_ipv6:
        errors.append('Mask too large for ipv6')

    services = {}

    # check if network exists
    if not errors:
        exists_network = db.select_project_network_by_ip(current_project['id'],
                                                         form.ip.data, form.mask.data)
        if exists_network:
            errors.append('Network exists!')

    # check port_id variable
    if not errors:
        for port_id in form.ip_port.data:
            if not db.check_port_in_project(current_project['id'], port_id):
                errors.append('Some ports are not in project!')
            else:
                if port_id in services:
                    if "0" not in services[port_id]:
                        services[port_id].append("0")
                else:
                    services[port_id] = ["0"]

    # check host_id variable
    if not errors:
        for host_port in form.host_port.data:
            port_id = host_port.split(':')[0]
            hostname_id = host_port.split(':')[1]
            port_data = db.select_port(port_id)
            hostname_data = db.select_hostname(hostname_id)
            if not port_data or not hostname_data:
                errors.append('Hostname not found error!')
            else:
                if port_data[0]['host_id'] != hostname_data[0]['host_id']:
                    errors.append('Some ports are not with these hostnames.')
                else:
                    if port_id not in services:
                        services[port_id] = [hostname_id]
                    else:
                        if hostname_id not in services[port_id]:
                            services[port_id].append(hostname_id)

    if not errors:
        network_id = db.insert_new_network(form.ip.data, form.mask.data,
                                           form.asn.data, form.comment.data,
                                           current_project['id'],
                                           current_user['id'], is_ipv6,
                                           form.internal_ip.data,
                                           form.cmd.data, services, form.name.data)
        return redirect('/project/{}/networks/'.format(current_project['id']))

    return render_template('project/networks/new.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='New network')


@routes.route('/project/<uuid:project_id>/networks/<uuid:network_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_network
@send_log_data
def project_network_info(project_id, current_project, current_user,
                         network_id, current_network):
    return render_template('project/networks/edit.html',
                           current_project=current_project,
                           current_network=current_network,
                           tab_name=current_network['ip'] + '/' + str(current_network['mask']))


@routes.route('/project/<uuid:project_id>/networks/<uuid:network_id>/edit',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_network
@send_log_data
def project_network_edit(project_id, current_project, current_user,
                         network_id, current_network):
    form = EditNetwork()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)
    else:
        if form.action.data == 'Delete':
            db.delete_network_safe(current_network['id'])

    is_ipv6 = False

    if not errors:
        is_ipv6 = ':' in form.ip.data

    if form.mask.data > 32 and not is_ipv6:
        errors.append('Mask too large for ipv4')

    if form.mask.data > 128 and is_ipv6:
        errors.append('Mask too large for ipv6')

    services = {}

    # check if network exists
    if not errors:
        exists_networks = db.select_project_network_by_ip(current_project['id'],
                                                          form.ip.data, form.mask.data)
        for network in exists_networks:
            if network['id'] != current_network['id']:
                errors.append('Network does not exist!')

    # check port_id variable
    if not errors:
        for port_id in form.ip_port.data:
            if not db.check_port_in_project(current_project['id'], port_id):
                errors.append('Some ports are not in project!')
            else:
                if port_id in services:
                    if "0" not in services[port_id]:
                        services[port_id].append("0")
                else:
                    services[port_id] = ["0"]

    # check host_id variable
    if not errors:
        for host_port in form.host_port.data:
            port_id = host_port.split(':')[0]
            hostname_id = host_port.split(':')[1]
            port_data = db.select_port(port_id)
            hostname_data = db.select_hostname(hostname_id)
            if not port_data or not hostname_data:
                errors.append('Hostname not found error!')
            else:
                if port_data[0]['host_id'] != hostname_data[0]['host_id']:
                    errors.append('Some ports are not with these hostnames.')
                else:
                    if port_id not in services:
                        services[port_id] = [hostname_id]
                    else:
                        if hostname_id not in services[port_id]:
                            services[port_id].append(hostname_id)

    if not errors:
        db.update_network(current_network['id'],
                          current_project['id'],
                          form.ip.data,
                          form.mask.data,
                          form.asn.data,
                          form.comment.data,
                          is_ipv6,
                          form.internal_ip.data,
                          form.cmd.data,
                          services,
                          form.name.data)
        return redirect('/project/{}/networks/{}/'.format(current_project['id'], current_network['id']))

    return render_template('project/networks/edit.html',
                           current_project=current_project,
                           current_network=current_network,
                           errors=errors,
                           tab_name=current_network['ip'] + '/' + str(current_network['mask']))


@routes.route('/project/<uuid:project_id>/networks/add_path',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_path_form(project_id, current_project, current_user):
    form = NewPath()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    host_out = ''
    network_out = ''
    host_in = ''
    network_in = ''

    if not errors:
        if form.type_out.data == 'host':
            host_id = form.out_id.data
            current_host = db.select_host(host_id)
            if not current_host or current_host[0]['project_id'] != current_project['id']:
                errors.append('Wrong HOST_ID!')
            else:
                host_out = current_host[0]['id']
        else:
            network_id = form.out_id.data
            current_network = db.select_network(network_id)
            if not current_network or current_network[0]['project_id'] != current_project['id']:
                errors.append('Wrong NETWORK_ID!')
            else:
                network_out = current_network[0]['id']
        if form.type_in.data == 'host':
            host_id = form.in_id.data
            current_host = db.select_host(host_id)
            if not current_host or current_host[0]['project_id'] != current_project['id']:
                errors.append('Wrong HOST_ID!')
            else:
                host_in = current_host[0]['id']
        else:
            network_id = form.in_id.data
            current_network = db.select_network(network_id)
            if not current_network or current_network[0]['project_id'] != current_project['id']:
                errors.append('Wrong NETWORK_ID!')
            else:
                network_in = current_network[0]['id']
    added = 0
    if not errors:
        if (network_in != '' and network_in == network_out) or (host_in != '' and host_in == host_out):
            errors.append('Source and destination are the same!')
        else:
            dublicate_paths = db.search_path(project_id=current_project['id'],
                                             out_host=host_out,
                                             out_network=network_out,
                                             in_host=host_in,
                                             in_network=network_in)
            if dublicate_paths:
                db.update_path_description_type(dublicate_paths[0]['id'],
                                                description=form.description.data,
                                                path_type=form.type.data,
                                                direction=form.direction.data)
                added = 1

    if not errors and not added:
        path_id = db.insert_path(project_id=current_project['id'],
                                 out_host=host_out,
                                 out_network=network_out,
                                 in_host=host_in,
                                 in_network=network_in,
                                 description=form.description.data,
                                 path_type=form.type.data,
                                 direction=form.direction.data)

    return render_template('project/networks/list.html',
                           current_project=current_project,
                           tab_name='Networks',
                           errors=errors)


@routes.route('/project/<uuid:project_id>/networks/delete_path',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def delete_path_form(project_id, current_project, current_user):
    form = DeletePath()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)
    if not errors:
        db.delete_path(path_id=form.path_id.data,
                       project_id=current_project['id'])

    return redirect('/project/{}/networks/#/paths'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/credentials/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_credentials(project_id, current_project, current_user):
    return render_template('project/creds/list.html',
                           current_project=current_project,
                           tab_name='Users')


@routes.route('/project/<uuid:project_id>/credentials/new_creds',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_add_credentials(project_id, current_project, current_user):
    return render_template('project/creds/new.html',
                           current_project=current_project,
                           tab_name='New User')


@routes.route('/project/<uuid:project_id>/credentials/new_creds',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_add_credentials_form(project_id, current_project, current_user):
    form = NewCredentials()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                if type(error) == list:
                    errors += error
                else:
                    errors.append(error)

    services = {}

    # check port_id variable
    if not errors:
        for port_id in form.ip_port.data:
            if not db.check_port_in_project(current_project['id'], port_id):
                errors.append('Some ports are not in project!')
            else:
                if port_id in services:
                    if "0" not in services[port_id]:
                        services[port_id].append("0")
                else:
                    services[port_id] = ["0"]

    # check host_id variable
    if not errors:
        for host_port in form.host_port.data:
            port_id = host_port.split(':')[0]
            hostname_id = host_port.split(':')[1]
            port_data = db.select_port(port_id)
            hostname_data = db.select_hostname(hostname_id)
            if not port_data or not hostname_data:
                errors.append('Hostname not found error!')
            else:
                if port_data[0]['host_id'] != hostname_data[0]['host_id']:
                    errors.append('Some ports are not with these hostnames.')
                else:
                    if port_id not in services:
                        services[port_id] = [hostname_id]
                    else:
                        if hostname_id not in services[port_id]:
                            services[port_id].append(hostname_id)

    if not errors:
        if form.check_pwd.data != '' and form.password_hash.data != '' and \
                form.hash_type.data != '':
            # TODO: add more hashes
            hash_function = ''
            if form.hash_type.data == 'md5_hex':
                hash_function = md5_hex_str
                form.password_hash.data = form.password_hash.data.lower()
            elif form.hash_type.data == 'sha1_hex':
                hash_function = sha1_hex_str
                form.password_hash.data = form.password_hash.data.lower()
            elif form.hash_type.data == 'sha256_hex':
                hash_function = sha256_hex_str
                form.password_hash.data = form.password_hash.data.lower()
            elif form.hash_type.data == 'sha512_hex':
                hash_function = sha512_hex_str
                form.password_hash.data = form.password_hash.data.lower()
            elif form.hash_type.data == 'md5_crypt_unix':
                try:
                    salt = form.password_hash.data.split('$')[2]
                    hash_function = lambda clr_str: md5_crypt_str(clr_str,
                                                                  salt)
                except Exception as e:
                    pass
            elif form.hash_type.data == 'rabbitmq_md5':
                try:
                    salt = base64.b64decode(form.password_hash.data)[:4]
                    hash_function = lambda clr_str: rabbitmq_md5_str(clr_str,
                                                                     salt)
                except Exception as e:
                    pass
            elif form.hash_type.data == 'des_crypt_unix':
                try:
                    salt = form.password_hash.data[:2]
                    hash_function = lambda clr_str: des_crypt_str(clr_str,
                                                                  salt)
                except Exception as e:
                    pass
            elif form.hash_type.data == 'sha512_crypt_unix':
                try:
                    salt = form.password_hash.data.split('$')[2]
                    hash_function = lambda clr_str: sha512_crypt_str(clr_str,
                                                                     salt)
                except Exception as e:
                    pass
            elif form.hash_type.data == 'sha256_crypt_unix':
                try:
                    salt = form.password_hash.data.split('$')[2]
                    hash_function = lambda clr_str: sha256_crypt_str(clr_str,
                                                                     salt)
                except Exception as e:
                    pass
            elif form.hash_type.data == 'ntlm_hex':
                hash_function = nt_hex_str
                form.password_hash.data = form.password_hash.data.lower()
            elif form.hash_type.data == 'lm_hex':
                hash_function = lm_hex_str
                form.password_hash.data = form.password_hash.data.lower()

            dict_file_path = ''
            if form.check_pwd.data == 'top10k':
                dict_file_path = config['bruteforce']['top10k']
            elif form.check_pwd.data == 'top100':
                dict_file_path = ''

            if dict_file_path != '' and hash_function != '':
                dict_file_obj = open(dict_file_path)
                dict_list = dict_file_obj.read().split('\n')
                dict_file_obj.close()
                for cleartext_pwd in dict_list:
                    if hash_function(
                            cleartext_pwd) == form.password_hash.data.strip():
                        form.cleartext_password.data = cleartext_pwd

    if not errors:
        creds_id = db.insert_new_cred(form.login.data, form.password_hash.data,
                                      form.hash_type.data,
                                      form.cleartext_password.data,
                                      form.comment.data,
                                      form.info_source.data,
                                      services,
                                      current_user['id'], current_project['id'])
        return redirect(
            '/project/{}/credentials/new_creds'.format(current_project['id']))

    return render_template('project/creds/new.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='New User')


@routes.route('/project/<uuid:project_id>/credentials/import_creds',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_add_credentials_multiple(project_id, current_project, current_user):
    return render_template('project/creds/multiple.html',
                           current_project=current_project,
                           tab_name='Many Users')


@routes.route('/project/<uuid:project_id>/credentials/import_creds',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_add_credentials_multiple_form(project_id, current_project, current_user):
    form = MultipleAddCreds()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    file_data = ''
    if form.content.data == '' and not form.file.data:
        errors.append("File content does not exist!")
    if form.content.data != '':
        file_data = form.content.data
    if 'file' in request.files and request.files.get('file').filename:
        # if new file
        file = request.files.get('file')
        template_tmp_name = gen_uuid()
        tmp_path = path.join(config['main']['tmp_path'],
                             template_tmp_name)
        file.save(tmp_path)
        file.close()
        file_size = stat(tmp_path).st_size
        if file_size > int(config['files']['template_max_size']):
            remove(tmp_path)
            errors.append('File too large!')
        else:
            f = open(tmp_path)
            file_data = f.read()
            f.close()
            remove(tmp_path)
    if errors:
        return render_template('project/creds/multiple.html',
                               current_project=current_project, errors=errors,
                               tab_name='Many Users')

    # indexes check
    file_lines = file_data.split('\n')
    array_lines = [[y.strip("\n\r") for y in line.split(form.delimiter.data)] for line in file_lines]
    column_indexes = [
        form.login_num.data,
        form.hash_num.data,
        form.cleartext_num.data,
        form.comment_num.data,
        form.source_num.data,
        form.host_num.data,
    ]
    # without 0
    clr_column_indexes = list(filter(lambda a: a > 0, column_indexes))
    if not clr_column_indexes:
        errors.append("No column numbers were selected!")
    if len(clr_column_indexes) > len(set(clr_column_indexes)):
        errors.append("Some column indexes are same!")

    # check for IP
    if not errors:
        host_error = False
        try:
            if form.host.data:
                ipaddress.ip_address(form.host.data)
            if form.host_num.data:
                for line in array_lines:
                    tmp_host = line[form.host_num.data - 1]
                    ipaddress.ip_address(tmp_host)
        except Exception as e:
            host_error = True
        if host_error:
            errors.append("Your IP-field is wrong or one of input rows (IP column) is corrupted!")
    if errors:
        return render_template('project/creds/multiple.html',
                               current_project=current_project, errors=errors,
                               tab_name='Many Users')

    if form.do_not_check_columns.data != '1':
        error = 0
        for line in array_lines:
            if max(clr_column_indexes) > len(line):
                error = 1
        if error:
            errors.append("Some rows are incorrect! len(columns) less than index of searching column")

    if errors:
        return render_template('project/creds/multiple.html',
                               current_project=current_project, errors=errors,
                               tab_name='Many Users')
    # prepare for bruteforce
    if form.check_pwd.data != '':
        dict_file_path = ''
        if form.check_pwd.data == 'top10k':
            dict_file_path = config['bruteforce']['top10k']
        elif form.check_pwd.data == 'top100':
            dict_file_path = ''
        if dict_file_path:
            f = open(dict_file_path)
            dict_words = f.read().split('\n')
            f.close()

    for line in array_lines:
        login = form.login.data
        hash = form.password_hash.data
        cleartext = form.cleartext_password.data
        comment = form.comment.data
        source = form.info_source.data
        host = form.host.data
        if form.login_num.data > 0:
            login = line[form.login_num.data - 1]
        if form.hash_num.data > 0:
            hash = line[form.hash_num.data - 1]
        if form.cleartext_num.data > 0:
            cleartext = line[form.cleartext_num.data - 1]
        if form.source_num.data > 0:
            login = line[form.source_num.data - 1]
        if form.host_num.data > 0:
            host = line[form.host_num.data - 1]

        host_id = None
        port_id = None
        services_dict = {}

        if host:
            # check if host exists

            # rechecking of string
            host_obj = ipaddress.ip_address(host)

            host_id = db.select_project_host_by_ip(current_project['id'], host)

            if host_id:
                host_id = host_id[0]['id']
            else:
                host_id = db.insert_host(current_project['id'], host, current_user['id'],
                                         "Source: Multiple credentials form")

            port_id = db.select_host_port(host_id)[0]['id']
            services_dict[port_id] = ["0"]

        found_duplicate = False
        # Always true for now. (TODO!!!)
        if form.do_not_check_dublicates.data == 0:
            found_list = db.select_creds_dublicates(current_project['id'], login, hash,
                                                    cleartext, comment, source,
                                                    form.hash_type.data)
            if found_list and port_id:
                found_duplicate = True
                for found_cred in found_list:
                    j = json.loads(found_cred['services'])
                    edited = False
                    if port_id not in j:
                        j[port_id] = ["0"]
                        edited = True
                    else:
                        if "0" not in j[port_id]:
                            j[port_id].append("0")
                            edited = True

                    if edited:
                        db.update_creds(found_cred['id'], found_cred['login'],
                                        found_cred['hash'], found_cred['hash_type'],
                                        found_cred['cleartext'], found_cred['description'],
                                        found_cred['source'], j)

        if not found_duplicate:
            if form.check_pwd.data != '' and hash != '' and \
                    form.hash_type.data != '':
                # TODO: add more hashes
                hash_function = ''
                if form.hash_type.data == 'md5_hex':
                    hash_function = md5_hex_str
                    form.password_hash.data = hash.lower()
                elif form.hash_type.data == 'sha1_hex':
                    hash_function = sha1_hex_str
                    form.password_hash.data = hash.lower()
                elif form.hash_type.data == 'sha256_hex':
                    hash_function = sha256_hex_str
                    form.password_hash.data = hash.lower()
                elif form.hash_type.data == 'sha512_hex':
                    hash_function = sha512_hex_str
                    form.password_hash.data = hash.lower()
                elif form.hash_type.data == 'md5_crypt_unix':
                    try:
                        salt = hash.split('$')[2]
                        hash_function = lambda clr_str: md5_crypt_str(clr_str,
                                                                      salt)
                    except Exception as e:
                        pass
                elif form.hash_type.data == 'rabbitmq_md5':
                    try:
                        salt = base64.b64decode(hash)[:4]
                        hash_function = lambda clr_str: rabbitmq_md5_str(clr_str,
                                                                         salt)
                    except Exception as e:
                        pass
                elif form.hash_type.data == 'des_crypt_unix':
                    try:
                        salt = hash[:2]
                        hash_function = lambda clr_str: des_crypt_str(clr_str,
                                                                      salt)
                    except Exception as e:
                        pass
                elif form.hash_type.data == 'sha512_crypt_unix':
                    try:
                        salt = hash.split('$')[2]
                        hash_function = lambda clr_str: sha512_crypt_str(clr_str,
                                                                         salt)
                    except Exception as e:
                        pass
                elif form.hash_type.data == 'sha256_crypt_unix':
                    try:
                        salt = hash.split('$')[2]
                        hash_function = lambda clr_str: sha256_crypt_str(clr_str,
                                                                         salt)
                    except Exception as e:
                        pass
                elif form.hash_type.data == 'ntlm_hex':
                    hash_function = nt_hex_str
                    form.password_hash.data = hash.lower()
                elif form.hash_type.data == 'lm_hex':
                    hash_function = lm_hex_str
                    form.password_hash.data = hash.lower()

                if dict_words and hash_function != '':
                    for cleartext_pwd in dict_words:
                        if hash_function(
                                cleartext_pwd) == hash.strip():
                            cleartext = cleartext_pwd

            if not errors:
                creds_id = db.insert_new_cred(login, hash,
                                              form.hash_type.data,
                                              cleartext,
                                              comment,
                                              source,
                                              services_dict,
                                              current_user['id'], current_project['id'])

    return render_template('project/creds/multiple.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='Many Users')


##################################
@routes.route('/project/<uuid:project_id>/credentials/<uuid:creds_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_creds
@send_log_data
def project_credentials_info(project_id, current_project, current_user,
                             creds_id, current_creds):
    return render_template('project/creds/edit.html',
                           current_project=current_project,
                           current_creds=current_creds,
                           tab_name='User info' if not current_creds['login'] else 'Login: {}'.format(
                               current_creds['login']))


@routes.route('/project/<uuid:project_id>/credentials/<uuid:creds_id>/',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_creds
@send_log_data
def project_credentials_info_form(project_id, current_project, current_user,
                                  creds_id, current_creds):
    form = UpdateCredentials()

    form.validate()
    errors = []

    if form.action.data == 'delete':
        db.delete_creds(current_creds['id'])
        return redirect(
            '/project/{}/credentials/'.format(current_project['id']))

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                if type(error) == list:
                    errors += error
                else:
                    errors.append(error)

    services = {}

    # check port_id variable
    if not errors:
        for port_id in form.ip_port.data:
            if not db.check_port_in_project(current_project['id'], port_id):
                errors.append('Some ports are not in project!')
            else:
                if port_id in services:
                    if "0" not in services[port_id]:
                        services[port_id].append("0")
                else:
                    services[port_id] = ["0"]

    # check host_id variable
    if not errors:
        for host_port in form.host_port.data:
            port_id = host_port.split(':')[0]
            hostname_id = host_port.split(':')[1]
            port_data = db.select_port(port_id)
            hostname_data = db.select_hostname(hostname_id)
            if not port_data or not hostname_data:
                errors.append('Hostname not found error!')
            else:
                if port_data[0]['host_id'] != hostname_data[0]['host_id']:
                    errors.append('Some ports are not with these hostnames.')
                else:
                    if port_id not in services:
                        services[port_id] = [hostname_id]
                    else:
                        if hostname_id not in services[port_id]:
                            services[port_id].append(hostname_id)

    if not errors:
        creds_id = db.update_creds(current_creds['id'],
                                   form.login.data,
                                   form.password_hash.data,
                                   form.hash_type.data,
                                   form.cleartext_password.data,
                                   form.comment.data,
                                   form.info_source.data,
                                   services)

    current_creds = db.select_creds(current_creds['id'])[0]
    return render_template('project/creds/edit.html',
                           current_project=current_project,
                           current_creds=current_creds,
                           errors=errors,
                           tab_name='User info' if not current_creds['login'] else 'Login: {}'.format(
                               current_creds['login'])
                           )


@routes.route('/project/<uuid:project_id>/credentials/export',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_credentials_export(project_id, current_project, current_user):
    form = ExportCredsForm()
    form.validate()

    if not form.errors:
        creds_array = db.select_project_creds(current_project['id'])
        result = []

        wordlist_passwords = []
        for wordlist in form.password_wordlist.data:
            if wordlist == 'top10k':
                f = open(config['bruteforce']['top10k'])
                wordlist_passwords += f.read().split('\n')
                f.close()
            elif wordlist == 'top1000':
                f = open(config['bruteforce']['top1000'])
                wordlist_passwords += f.read().split('\n')
                f.close()
            elif wordlist == 'top100':
                f = open(config['bruteforce']['top100'])
                wordlist_passwords += f.read().split('\n')
                f.close()

        wordlist_passwords = list(set(wordlist_passwords))

        users_arr = list(
            set([current_creds['login'] for current_creds in creds_array]))
        passwords_arr = list(
            set([current_creds['cleartext'] for current_creds in creds_array]))

        if not form.empty_passwords.data and '' in passwords_arr:
            del passwords_arr[passwords_arr.index('')]

        if form.login_as_password.data:
            passwords_arr += users_arr
            passwords_arr = list(set(passwords_arr))

        if form.export_type.data == 'usernames':
            result = users_arr
        elif form.export_type.data == 'passwords':
            passwords_arr += wordlist_passwords
            result = list(set(passwords_arr))
        elif form.export_type.data == 'user_pass':
            for current_creds in creds_array:
                if form.empty_passwords.data or \
                        (not form.empty_passwords.data
                         and '' != current_creds['cleartext']):
                    result.append('{}{}{}'.format(current_creds['login'],
                                                  form.divider.data,
                                                  current_creds['cleartext']))
        elif form.export_type.data == 'user_pass_variations':
            passwords_arr = list(set(passwords_arr + wordlist_passwords))
            for user in users_arr:
                for password in passwords_arr:
                    result.append('{}{}{}'.format(user,
                                                  form.divider.data,
                                                  password))

        if form.show_in_browser.data:
            return Response('\n'.join(result),
                            mimetype="text/plain")

        return Response('\n'.join(result),
                        mimetype="text/plain",
                        headers={
                            "Content-disposition": "attachment; filename=passwords.txt"})
    return redirect(
        '/project/{}/credentials/'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/notes/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_notes(project_id, current_project, current_user):
    return render_template('project/notes/index.html',
                           current_project=current_project,
                           tab_name='Notes')


@routes.route('/project/<uuid:project_id>/print_note/<uuid:note_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_note_access
@send_log_data
def project_print_note(project_id, current_project, current_user, note_id, current_note):
    return render_template('project/notes/print_note.html',
                           current_project=current_project,
                           current_note=current_note,
                           current_user=current_user)


@routes.route('/project/<uuid:project_id>/notes/add',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_note_form(project_id, current_project, current_user):
    form = NewNote()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    host_id = ''
    if not errors and form.host_id.data:
        if not is_valid_uuid(form.host_id.data):
            errors.append('Invalid host id')
        else:
            current_host = db.select_project_host(current_project['id'], form.host_id.data)
            if not current_host:
                errors.append('Invalid host id')
            else:
                host_id = current_host[0]['id']

    note_id = ""

    if not errors:
        if form.note_type.data == "google_drive":
            # check url for google drive
            if urlparse(form.url.data).netloc.lower() == "docs.google.com":
                note_id = db.insert_new_note(current_project['id'], form.name.data,
                                             current_user['id'], host_id=host_id, note_type=form.note_type.data,
                                             text=form.url.data)
        elif form.note_type.data == "excalidraw":
            # check url for excalidraw
            if urlparse(form.url.data).netloc.lower() == "excalidraw.com":
                note_id = db.insert_new_note(current_project['id'], form.name.data,
                                             current_user['id'], host_id=host_id, note_type=form.note_type.data,
                                             text=form.url.data)
        elif form.note_type.data == "url":
            if urlparse(form.url.data).scheme.lower() in ["http", "https"]:
                note_id = db.insert_new_note(current_project['id'], form.name.data,
                                             current_user['id'], host_id=host_id, note_type=form.note_type.data,
                                             text=form.url.data)

        elif form.note_type.data in ["markdown", "html", "plaintext"]:
            note_id = db.insert_new_note(current_project['id'], form.name.data,
                                         current_user['id'], host_id=host_id, note_type=form.note_type.data)

    referer = request.headers.get("Referer")
    if '/host/' in referer:
        referer += '#/notes/'
        if note_id:
            referer += 'note_' + note_id
    return redirect(referer)


@routes.route('/project/<uuid:project_id>/notes/edit',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def edit_note_form(project_id, current_project, current_user):
    form = EditNote()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:

        current_note = db.select_project_note(current_project['id'], form.note_id.data)
        if not current_note:
            return redirect('/project/{}/notes/'.format(current_project['id']))

        current_note = current_note[0]

        if form.action.data == 'Update' and current_note['type'] in ["html", "plaintext", "markdown"]:
            db.update_note(current_note['id'], form.text.data, current_project['id'])
        elif form.action.data == 'Delete':
            db.delete_note(current_note['id'], current_project['id'])
        elif form.action.data == 'Rename':
            db.update_note_name(current_note['id'], form.text.data, current_project['id'])

    return redirect('/project/{}/notes/'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/files/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_files(project_id, current_project, current_user):
    return render_template('project/files/list.html',
                           current_project=current_project,
                           tab_name='Files',
                           webdav=int(config['main']['webdav']),
                           webdav_project=re.sub('[^a-zA-Z0-9а-яА-Я]', '_', current_project['name']))


@routes.route('/project/<uuid:project_id>/files/new',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_new_file_form(project_id, current_project, current_user):
    form = NewFile()
    form.validate()

    referer = request.headers.get("Referer")

    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    # check port_id variable
    services = {}
    # check host_id variable
    if not errors:
        for host_port in form.services.data:
            port_id = host_port.split(':')[0]
            hostname_id = host_port.split(':')[1]
            port_data = db.select_project_port(current_project['id'], port_id)
            if not port_data:
                errors.append('Port not found!')
            port_data = port_data[0]
            if not errors:
                if hostname_id != '0':
                    hostname_data = db.select_project_hostname(current_project['id'], hostname_id)
                    if not hostname_data or hostname_data[0]['host_id'] != port_data['host_id']:
                        errors.append("Hostname not found!")
            if not errors:
                if port_id not in services:
                    services[port_id] = [hostname_id]
                else:
                    if hostname_id not in services[port_id]:
                        services[port_id].append(hostname_id)

    if not errors:
        file = request.files.get('file')
        file_id = gen_uuid()
        tmp_file_path = path.join(config['main']['tmp_path'], file_id)
        file.save(tmp_file_path)
        file.close()
        file_size = stat(tmp_file_path).st_size
        if file_size > int(config['files']['files_max_size']):
            remove(tmp_file_path)
            errors.append('File too large!')
        else:
            new_file_path = path.join('./static/files/code/', file_id)
            shutil.move(tmp_file_path, new_file_path)

            file_data = b''
            if config["files"]["files_storage"] == 'database':
                f = open(new_file_path, 'rb')
                file_data = f.read()
                f.close()
                remove(new_file_path)

            db.insert_new_file(file_id, current_project['id'], file.filename,
                               form.description.data,
                               services, form.filetype.data, current_user['id'],
                               storage=config["files"]["files_storage"],
                               data=file_data)
            if '/host/' in referer:
                return redirect(referer + '/#/files')
            else:
                return redirect('/project/{}/files/'.format(current_project['id']))

    if '/host/' in referer:
        return redirect(referer + '/#/files')
    else:
        return render_template('project/files/list.html',
                               current_project=current_project,
                               errors=errors,
                               tab_name='Files',
                               webdav=int(config['main']['webdav']),
                               webdav_project=re.sub('[^a-zA-Z0-9а-яА-Я]', '_', current_project['name']))


@routes.route('/project/<uuid:project_id>/files/<uuid:file_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_file_access
@send_log_data
def project_file_info(project_id, current_project, current_user, file_id,
                      current_file):
    return render_template('project/files/view.html',
                           current_project=current_project,
                           current_file=current_file,
                           tab_name=current_file['filename'])


@routes.route('/project/<uuid:project_id>/files/<uuid:file_id>/download',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_file_access
@send_log_data
def project_file_download(project_id, current_project, current_user, file_id, current_file):
    if current_file['storage'] == 'filesystem':
        return send_from_directory('static/files/code', str(current_file['id']),
                                   as_attachment=True,
                                   attachment_filename=current_file['filename'])
    elif current_file['storage'] == 'database':
        return send_file(
            BytesIO(base64.b64decode(current_file['base64'])),
            as_attachment=True,
            attachment_filename=current_file['filename'])
    return ''


@routes.route('/project/<uuid:project_id>/files/<uuid:file_id>/',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_project_file_access
@send_log_data
def project_file_edit(project_id, current_project, current_user, file_id,
                      current_file):
    form = EditFile()

    form.validate()

    errors = []

    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if form.action.data == 'delete':
        file_path = path.join('./static/files/code/', current_file['id'])
        if current_file['storage'] == 'filesystem':
            remove(file_path)
        db.delete_file(current_file['id'])
        referer = request.headers.get("Referer")
        if 'reports' in referer:
            return redirect(referer)
        elif '/host/' in referer:
            return redirect(referer + '/#/files')
        else:
            return redirect('/project/{}/files/'.format(current_project['id']))

    return render_template('project/files/view.html',
                           current_project=current_project,
                           current_file=current_file,
                           tab_name=current_file['filename'])


@routes.route('/project/<uuid:project_id>/settings/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_settings(project_id, current_project, current_user):
    return render_template('project/settings/index.html',
                           current_project=current_project,
                           tab_name='Settings',
                           current_user=current_user)


@routes.route('/project/<uuid:project_id>/settings/', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_settings_form(project_id, current_project, current_user):
    # team access check
    form = EditProjectSettings()
    form.validate()

    errors = []

    if form.errors:
        for field in form.errors:
            for err in form.errors[field]:
                errors.append(err)

    if form.action.data == 'Archive':
        db.update_project_status(current_project['id'], 0)
        return redirect(request.referrer)
    if form.action.data == 'Activate':
        db.update_project_status(current_project['id'], 1)
        db.update_project_autoarchive(current_project['id'], 0)
        return redirect(request.referrer)
    if form.action.data == 'Delete':
        if current_project['admin_id'] == current_user['id']:
            if config["main"]["delete_projects"] == "1":
                db.delete_project_safe(current_project['id'])
            else:
                db.update_project_status(current_project['id'], -1)
            return redirect('/projects/')
        else:
            errors.append('You are not a creator of this project!')

    # else action == 'Update'

    # check teams access
    if not errors:

        for team_id in form.teams.data:
            current_team = db.select_team_by_id(team_id)
            if not current_team:
                errors.append('Team {} does not exist!'.format(team_id))
            elif session['id'] not in current_team[0]['users']:
                errors.append(
                    'User does not have access to team {}!'.format(team_id))

    # check user relationship

    form_users = [user for user in form.users.data if user]
    teams_array = db.select_user_teams(session['id'])
    if not errors:
        for user_id in form_users:
            found = 0
            for team in teams_array:
                if user_id in team['users']:
                    found = 1
            if not found or not db.select_user_by_id(user_id):
                errors.append('User {} not found!'.format(user_id))

    if not errors:
        # creating project
        start_time = calendar.timegm(form.start_date.data.timetuple())
        end_time = calendar.timegm(form.end_date.data.timetuple())

        if current_user['id'] not in form_users:
            form_users.append(current_user['id'])

        project_id = db.update_project_settings(current_project['id'],
                                                form.name.data,
                                                form.description.data,
                                                form.project_type.data,
                                                form.scope.data,
                                                start_time,
                                                end_time,
                                                form.archive.data,
                                                form_users,
                                                form.teams.data,
                                                form.folder.data,
                                                form.report_title.data)
    current_project = db.check_user_project_access(current_project['id'],
                                                   session['id'])
    return render_template('project/settings/index.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='Settings',
                           current_user=current_user)


@routes.route('/project/<uuid:project_id>/settings/favorite', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_settings_favorite(project_id, current_project, current_user):
    session['current_user']['favorite'] = current_project['id']
    current_user['favorite'] = current_project['id']
    db.update_favorite_project(current_user['id'], current_project['id'])

    return 'OK'


@routes.route('/project/<uuid:project_id>/services/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_services(project_id, current_project, current_user):
    return render_template('project/services/list.html',
                           current_project=current_project,
                           tab_name='Services')


@routes.route('/project/<uuid:project_id>/services/new_service',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_new_services(project_id, current_project, current_user):
    return render_template('project/services/new.html',
                           current_project=current_project,
                           tab_name='New Service')


@routes.route('/project/<uuid:project_id>/services/new_service',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_new_services_form(project_id, current_project, current_user):
    form = MultiplePortHosts()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]

    port_type = 'tcp'
    if form.port.data.endswith('/udp'):
        port_type = 'udp'
    is_tcp = port_type == 'tcp'
    try:
        port_num = int(form.port.data.replace('/' + port_type, ''))
        if (port_num < 1) or (port_num > 65535):
            errors.append('UDP port number invalid {1..65535}')
    except ValueError:
        errors.append('Port number invalid format')

    if not form.host.data:
        errors.append('Hosts were not selected!')

    if not errors:
        for host_id in form.host.data:
            current_host = db.select_project_host(current_project['id'],
                                                  str(host_id))
            if current_host:
                db.insert_host_port(host_id, port_num, is_tcp,
                                    form.service.data, form.description.data,
                                    current_user['id'], current_project['id'])

    return render_template('project/services/new.html',
                           current_project=current_project,
                           errors=errors,
                           tab_name='New Service')


@routes.route('/project/<uuid:project_id>/reports/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_reports(project_id, current_project, current_user):
    example_files = {
        "./documentation/report/examples/security_analysis_docx/example.docx": ".docx - example report",
        "./documentation/report/examples/security_analysis_latex/security_analysis_latex.zip": ".tex - example report",
        "./documentation/report/examples/simple_txt/ip_hostnames_list.txt": ".csv - ip,hostname1,hostname2\\n",
        "./documentation/report/examples/simple_txt/ip_port_list_csv.txt": ".csv - ip;port;service;comment\\n",
        "./documentation/report/examples/simple_txt/issues_list_csv.txt": ".csv - Issue name,Status,Description,...\\n"
    }

    return render_template('project/reports/index.html',
                           current_project=current_project,
                           current_user=current_user,
                           tab_name='Reports', example_files=example_files)


@routes.route('/project/<uuid:project_id>/reports/export/json', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_report_export(project_id, current_project, current_user):
    project_dict = db.select_report_info_sorted(current_project['id'])
    for poc_id in project_dict['pocs']:
        project_dict['pocs'][poc_id]["content_base64"] = project_dict['pocs'][poc_id]["content_base64"].decode(
            'charmap')

    final_json = {
        "project": project_dict['project'],
        "issues": project_dict['issues'],
        "hosts": project_dict['hosts'],
        "pocs": project_dict['pocs'],
        "ports": project_dict['ports'],
        "hostnames": project_dict['hostnames'],
        "grouped_issues": project_dict['grouped_issues'],
        "tasks": project_dict['tasks'],
        "notes": project_dict['notes'],
        "paths": project_dict['paths'],
        "networks": project_dict['networks'],
        "credentials": project_dict['credentials']
    }

    return jsonify(final_json)


@routes.route('/project/<uuid:project_id>/chats/', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def project_chats(project_id, current_project, current_user):
    return render_template('project/chats/index.html',
                           current_project=current_project,
                           current_user=current_user,
                           tab_name='Chats')


@routes.route('/project/<uuid:project_id>/chats/add', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_new_chat(project_id, current_project, current_user):
    form = NewChat()

    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)
    if not errors:
        chat_id = db.insert_chat(current_project['id'],
                                 form.name.data,
                                 current_user['id'])
    return redirect('/project/{}/chats/'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/chats/<uuid:chat_id>/edit',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_chat_access
@send_log_data
def project_edit_chat_form(project_id, current_project, current_user, chat_id, current_chat):
    form = EditChat()

    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)
    if not errors:
        if form.action.data == 'delete':
            db.delete_chat(current_chat['id'])
            if form.del_messages.data:
                db.delete_chat_all_messages(current_chat['id'])
            return redirect('/project/{}/chats/'.format(current_project['id']))
        elif form.action.data == 'rename':
            db.update_chat_name(current_chat['id'], form.name.data)
            return redirect('/project/{}/chats/#/chat_{}'.format(current_project['id'], current_chat['id']))
    return redirect('/project/{}/chats/'.format(current_project['id']))


@routes.route('/project/<uuid:project_id>/chats/<uuid:chat_id>/getall.json',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_chat_access
@send_log_data
def project_chats_getall(project_id, current_project, current_user, chat_id,
                         current_chat):
    messages = db.select_chat_messages(current_chat['id'])
    users_arr = {}
    message_array = []
    for message in messages:
        # get email
        # TODO: change email to names
        if not message['user_id'] in users_arr:
            email = db.select_user_by_id(message['user_id'])[0]['email']
            users_arr[message['user_id']] = email
        else:
            email = users_arr[message['user_id']]

        message_array.append({'email': email,
                              'message': message['message'],
                              'time': message['time']})
    return jsonify(message_array)


@routes.route(
    '/project/<uuid:project_id>/chats/<uuid:chat_id>/getnewmessages/<int:last_msg_time>/',
    methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_chat_access
@send_log_data
def project_chats_getlastmsg(project_id, current_project, current_user, chat_id,
                             current_chat, last_msg_time):
    messages = db.select_chat_messages(current_chat['id'], last_msg_time)
    users_arr = {}
    message_array = []
    for message in messages:
        # get email
        # TODO: change email to names
        if not message['user_id'] in users_arr:
            email = db.select_user_by_id(message['user_id'])[0]['email']
            users_arr[message['user_id']] = email
        else:
            email = users_arr[message['user_id']]

        message_array.append({'email': email,
                              'message': message['message'],
                              'time': message['time']})
    return jsonify(message_array)


@routes.route('/project/<uuid:project_id>/chats/<uuid:chat_id>/sendmessage',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_chat_access
@send_log_data
def project_send_chat_message(project_id, current_project, current_user,
                              chat_id, current_chat):
    form = NewMessage()

    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)
    if not errors:
        message_time = db.insert_new_message(current_chat['id'],
                                             form.message.data,
                                             current_user['id'])
        return str(message_time)
    return 'Error!'


@routes.route('/share/issue/<uuid:issue_id>/',
              methods=['GET'])
def issues_info_share(issue_id):
    current_issue = db.select_issue(str(issue_id))
    if not current_issue:
        return redirect('/404')

    current_issue = current_issue[0]

    return render_template('project/issues/share.html',
                           current_issue=current_issue,
                           tab_name=current_issue['name'] if current_issue['name'] else 'Issue')


@routes.route('/project/<uuid:project_id>/reports/',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def generate_report(project_id, current_project, current_user):
    form = ReportGenerate()

    form.validate()
    errors = []
    unix_time = time.time()
    curr_time = datetime.datetime.fromtimestamp(int(unix_time)).strftime(config['design']['report_filename_date'])
    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    need_to_delete = True
    report_template = None
    if not errors:
        report_template = None
        need_to_delete = True
        if form.example_template.data:
            report_path = form.example_template.data
            need_to_delete = False
        elif 'file' in request.files and request.files.get('file').filename:
            # if new file
            file = request.files.get('file')
            template_tmp_name = gen_uuid()
            report_path = path.join(config['main']['tmp_path'],
                                    template_tmp_name)
            file.save(report_path)
            file.close()
            file_size = stat(report_path).st_size
            if file_size > int(config['files']['template_max_size']):
                remove(report_path)
                errors.append('File too large!')
        else:
            # exist template
            if is_valid_uuid(form.template_id.data):
                report_template = db.select_report_templates(template_id=form.template_id.data)
                if report_template:
                    report_template = report_template[0]
                    if report_template['storage'] == 'filesystem':
                        report_path = path.join('./static/files/templates/',
                                                form.template_id.data)
                    elif report_template['storage'] == 'database':
                        # creating tmp file
                        report_path = path.join(config['main']['tmp_path'], report_template['id'])
                        f = open(report_path, 'wb')
                        f.write(base64.b64decode(report_template['base64']))
                        f.close()
            else:
                errors.append('Wrong template id!')

    def clear_report(report_template_obj, report_path_str):
        if report_template_obj and 'storage' in report_template_obj and report_path_str:
            if report_template_obj['storage'] == 'database':
                remove(report_path_str)

    def isdir(z, name):
        return any(x.startswith("%s/" % name.rstrip("/")) for x in z.namelist())

    def isValidDocx(filename):
        f = zipfile.ZipFile(filename, "r")
        return isdir(f, "word") and isdir(f, "docProps") and isdir(f, "_rels")

    if not errors:
        def docx_image(image_id, width=None, height=None):
            if not is_valid_uuid(image_id):
                return None
            tmp_image_path = path.join(config['main']['tmp_path'],
                                       image_id + '.png')
            image_object = InlineImage(template_obj, tmp_image_path)
            if width and height:
                image_object = InlineImage(template_obj, tmp_image_path, width=Mm(width), height=Mm(height))
            elif width:
                image_object = InlineImage(template_obj, tmp_image_path, width=Mm(width))
            elif height:
                image_object = InlineImage(template_obj, tmp_image_path, height=Mm(height))
            else:
                image_object = InlineImage(template_obj, tmp_image_path)
            return image_object

        def docx_link(link_text, link_href):
            rt = RichText()
            rt.add(link_text, url_id=template_obj.build_url_id(link_href))
            return rt

        if zipfile.is_zipfile(report_path):
            if isValidDocx(report_path):
                # docx
                template_obj = DocxTemplate(report_path)
                project_dict = db.select_report_info_sorted(current_project['id'])
                docx_uuid = gen_uuid()
                result_docx_path = path.join(config['main']['tmp_path'],
                                             docx_uuid + '.docx')
                template_images = []

                def docx_image(image_id, width=None, height=None):
                    if not is_valid_uuid(image_id):
                        return None
                    tmp_image_path = path.join(config['main']['tmp_path'],
                                               image_id + '.png')
                    image_object = InlineImage(template_obj, tmp_image_path)
                    if width and height:
                        image_object = InlineImage(template_obj, tmp_image_path, width=Mm(width), height=Mm(height))
                    elif width:
                        image_object = InlineImage(template_obj, tmp_image_path, width=Mm(width))
                    elif height:
                        image_object = InlineImage(template_obj, tmp_image_path, height=Mm(height))
                    else:
                        image_object = InlineImage(template_obj, tmp_image_path)
                    return image_object

                def docx_link(link_text, link_href):
                    rt = RichText()
                    rt.add(link_text, url_id=template_obj.build_url_id(link_href))
                    return rt

                for poc_id in project_dict['pocs']:
                    project_dict['pocs'][poc_id]['content_image'] = None
                    if project_dict['pocs'][poc_id]['filetype'] == 'image':
                        tmp_image_id = poc_id
                        tmp_image_path = path.join(config['main']['tmp_path'],
                                                   tmp_image_id + '.png')
                        template_images.append(tmp_image_path)
                        if config['files']['poc_storage'] == 'filesystem':
                            original_image_path = path.join('./static/files/poc/', poc_id)
                            shutil.copyfile(original_image_path, tmp_image_path)
                        elif config['files']['poc_storage'] == 'database':
                            with open(tmp_image_path, 'wb') as f:
                                f.write(base64.b64decode(project_dict['pocs'][poc_id]['content_base64']))
                                f.close()
                        project_dict['pocs'][poc_id]['content_image'] = InlineImage(template_obj, tmp_image_path)
                try:
                    run_function_timeout(
                        template_obj.render, int(config["timeouts"]["report_timeout"]),
                        {
                            "project": project_dict['project'],
                            "issues": project_dict['issues'],
                            "hosts": project_dict['hosts'],
                            "pocs": project_dict['pocs'],
                            "ports": project_dict['ports'],
                            "hostnames": project_dict['hostnames'],
                            "grouped_issues": project_dict['grouped_issues'],
                            "tasks": project_dict['tasks'],
                            "docx_image": docx_image,
                            "notes": project_dict['notes'],
                            "paths": project_dict['paths'],
                            "networks": project_dict['networks'],
                            "credentials": project_dict['credentials'],
                            "functions": {
                                "format_date": lambda unix_time,
                                                      str_format: datetime.datetime.fromtimestamp(
                                    int(unix_time)).strftime(str_format),
                                "latex_escape": latex_str_escape,
                                "docx_image": docx_image,
                                "docx_link": docx_link,
                                "ips_in_subnets": lambda ip_arr, network_arr: True in [
                                    ipaddress.ip_address(ip) in ipaddress.ip_network(network, False) for ip in ip_arr
                                    for network in network_arr],
                                "group_issues_by": group_issues_by,
                                "csv_escape": csv_escape,
                                "issue_targets_list": issue_targets_list
                            }
                        },
                        jinja_env=SandboxedEnvironment(autoescape=True)
                    )
                    template_obj.save(result_docx_path)
                    result_file = open(result_docx_path, 'rb')
                    result_data = result_file.read()
                    result_file.close()
                except Exception as e:
                    for image_tmp_path in template_images:
                        remove(image_tmp_path)
                    clear_report(report_template, report_path)
                    return render_template(
                        'project/reports/index.html',
                        current_project=current_project,
                        current_user=current_user,
                        errors=errors,
                        exception=e)

                for image_tmp_path in template_images:
                    remove(image_tmp_path)

                file_uuid = docx_uuid
                shutil.move(result_docx_path, './static/files/code/' + file_uuid)

                file_data = b''

                if config["files"]["files_storage"] == 'database':
                    f = open('./static/files/code/' + file_uuid, 'rb')
                    file_data = f.read()
                    f.close()
                    remove('./static/files/code/' + file_uuid)

                db.insert_new_file(file_uuid, current_project['id'],
                                   'report_' + curr_time + '.docx',
                                   str(int(time.time())), '{}', 'report',
                                   current_user['id'], storage=config["files"]["files_storage"],
                                   data=file_data)

                clear_report(report_template, report_path)
                return Response(result_data,
                                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                headers={
                                    "Content-disposition":
                                        "attachment; filename=report_{}.docx".format(curr_time)})

            else:
                # zip with latex
                zipfile_obj = zipfile.ZipFile(report_path, 'r')
                zip_unpack_size = sum([zinfo.file_size for zinfo
                                       in zipfile_obj.filelist])
                if zip_unpack_size > int(config['files']['template_max_size']):
                    errors.append('Unpacked ZIP too large!')
                zip_uuid = gen_uuid()
                zip_unpacked_path = path.join(config['main']['tmp_path'], zip_uuid)
                makedirs(zip_unpacked_path)
                zipfile_obj.extractall(zip_unpacked_path)
                zipfile_obj.close()
                if 'file' in request.files and request.files.get('file').filename and need_to_delete:
                    remove(report_path)
                result_zip_path = path.join(config['main']['tmp_path'],
                                            zip_uuid + '.zip')
                result_zip_obj = zipfile.ZipFile(result_zip_path, 'w',
                                                 zipfile.ZIP_DEFLATED)
                project_dict = db.select_report_info_sorted(current_project['id'])
                for root, dirs, files in walk(zip_unpacked_path):
                    for file in files:
                        file_path = path.join(root, file)
                        file_ext = file.split('.')[-1].lower()
                        if file_ext in form.extentions.data.split(','):
                            if file_ext == 'docx':
                                pass
                            else:
                                f = open(file_path, encoding='utf-8')
                                template_data = ''
                                try:
                                    template_data = f.read()
                                except:
                                    print('Error reading ' + file_path)
                                f.close()
                            if file_ext == 'docx' or template_data:
                                if file_ext != 'docx':
                                    env = SandboxedEnvironment(autoescape=True)
                                    template_obj = env.from_string(template_data)
                                try:
                                    if file_ext == 'docx':
                                        if isValidDocx(file_path):
                                            # docx
                                            template_obj = DocxTemplate(file_path)
                                            docx_uuid = gen_uuid()
                                            result_docx_path = path.join(config['main']['tmp_path'],
                                                                         docx_uuid + '.docx')
                                            template_images = []

                                            def docx_image(image_id, width=None, height=None):
                                                if not is_valid_uuid(image_id):
                                                    return None
                                                tmp_image_path = path.join(config['main']['tmp_path'],
                                                                           image_id + '.png')
                                                image_object = InlineImage(template_obj, tmp_image_path)
                                                if width and height:
                                                    image_object = InlineImage(template_obj, tmp_image_path,
                                                                               width=Mm(width), height=Mm(height))
                                                elif width:
                                                    image_object = InlineImage(template_obj, tmp_image_path,
                                                                               width=Mm(width))
                                                elif height:
                                                    image_object = InlineImage(template_obj, tmp_image_path,
                                                                               height=Mm(height))
                                                else:
                                                    image_object = InlineImage(template_obj, tmp_image_path)
                                                return image_object

                                            def docx_link(link_text, link_href):
                                                rt = RichText()
                                                rt.add(link_text, url_id=template_obj.build_url_id(link_href))
                                                return rt

                                            for poc_id in project_dict['pocs']:
                                                project_dict['pocs'][poc_id]['content_image'] = None
                                                if project_dict['pocs'][poc_id]['filetype'] == 'image':
                                                    tmp_image_id = poc_id
                                                    tmp_image_path = path.join(config['main']['tmp_path'],
                                                                               tmp_image_id + '.png')
                                                    template_images.append(tmp_image_path)
                                                    if config['files']['poc_storage'] == 'filesystem':
                                                        original_image_path = path.join('./static/files/poc/', poc_id)
                                                        shutil.copyfile(original_image_path, tmp_image_path)
                                                    elif config['files']['poc_storage'] == 'database':
                                                        with open(tmp_image_path, 'wb') as f:
                                                            f.write(base64.b64decode(
                                                                project_dict['pocs'][poc_id]['content_base64']))
                                                            f.close()

                                                    project_dict['pocs'][poc_id]['content_image'] = InlineImage(
                                                        template_obj, tmp_image_path)
                                            run_function_timeout(
                                                template_obj.render, int(config["timeouts"]["report_timeout"]),
                                                {
                                                    "project": project_dict['project'],
                                                    "issues": project_dict['issues'],
                                                    "hosts": project_dict['hosts'],
                                                    "pocs": project_dict['pocs'],
                                                    "ports": project_dict['ports'],
                                                    "hostnames": project_dict['hostnames'],
                                                    "grouped_issues": project_dict['grouped_issues'],
                                                    "tasks": project_dict['tasks'],
                                                    "docx_image": docx_image,
                                                    "notes": project_dict['notes'],
                                                    "paths": project_dict['paths'],
                                                    "networks": project_dict['networks'],
                                                    "credentials": project_dict['credentials'],
                                                    "functions": {
                                                        "format_date": lambda unix_time,
                                                                              str_format: datetime.datetime.fromtimestamp(
                                                            int(unix_time)).strftime(str_format),
                                                        "latex_escape": latex_str_escape,
                                                        "docx_image": docx_image,
                                                        "docx_link": docx_link,
                                                        "ips_in_subnets": lambda ip_arr, network_arr: True in [
                                                            ipaddress.ip_address(ip) in ipaddress.ip_network(network,
                                                                                                             False) for
                                                            ip in ip_arr for network in network_arr],
                                                        "group_issues_by": group_issues_by,
                                                        "csv_escape": csv_escape,
                                                        "issue_targets_list": issue_targets_list
                                                    }
                                                },
                                                jinja_env=SandboxedEnvironment(autoescape=True)
                                            )
                                            template_obj.save(result_docx_path)
                                            shutil.move(result_docx_path, file_path)
                                    else:
                                        rendered_txt = run_function_timeout(
                                            template_obj.render, int(config["timeouts"]["report_timeout"]),
                                            project=project_dict['project'],
                                            issues=project_dict['issues'],
                                            hosts=project_dict['hosts'],
                                            pocs=project_dict['pocs'],
                                            ports=project_dict['ports'],
                                            hostnames=project_dict['hostnames'],
                                            grouped_issues=project_dict['grouped_issues'],
                                            tasks=project_dict['tasks'],
                                            notes=project_dict['notes'],
                                            paths=project_dict['paths'],
                                            networks=project_dict['networks'],
                                            credentials=project_dict['credentials'],
                                            latex_escape=latex_str_escape,
                                            functions={
                                                "format_date": lambda unix_time,
                                                                      str_format: datetime.datetime.fromtimestamp(
                                                    int(unix_time)).strftime(str_format),
                                                "latex_escape": latex_str_escape,
                                                "ips_in_subnets": lambda ip_arr, network_arr: True in [
                                                    ipaddress.ip_address(ip) in ipaddress.ip_network(network, False) for
                                                    ip in ip_arr for network in network_arr],
                                                "group_issues_by": group_issues_by,
                                                "csv_escape": csv_escape,
                                                "issue_targets_list": issue_targets_list
                                            }
                                        )
                                        f = open(file_path, 'w', encoding='utf-8')
                                        f.write(rendered_txt)
                                        f.close()
                                except Exception as e:
                                    shutil.rmtree(zip_unpacked_path)
                                    clear_report(report_template, report_path)
                                    return render_template(
                                        'project/reports/index.html',
                                        current_project=current_project,
                                        current_user=current_user,
                                        errors=errors,
                                        exception=e)
                        result_zip_obj.write(file_path)

                # add PoC to zip

                poc_save_dir = path.join(zip_unpacked_path, 'poc_files')
                makedirs(poc_save_dir)
                for current_poc in db.select_project_pocs(current_project['id']):
                    if current_poc['type'] == 'text':
                        poc_save_path = path.join(poc_save_dir,
                                                  current_poc['id'] + '.txt')
                    elif current_poc['type'] == 'image':
                        poc_save_path = path.join(poc_save_dir,
                                                  current_poc['id'] + '.png')
                    elif current_poc['type'] == 'document':
                        if current_poc['filename'].lower().endswith('.pdf'):
                            poc_save_path = path.join(poc_save_dir,
                                                      current_poc['id'] + '.pdf')
                        else:
                            poc_save_path = path.join(poc_save_dir,
                                                      current_poc['id'] + '.docx')
                    if current_poc['storage'] == 'filesystem':
                        poc_server_path = path.join(path.join('./static/files/poc/',
                                                              current_poc['id']))
                        shutil.copyfile(poc_server_path, poc_save_path)
                    elif current_poc['storage'] == 'database':
                        content_b = base64.b64decode(current_poc['base64'])
                        f = open(poc_save_path, 'wb')
                        f.write(content_b)
                        f.close()
                    result_zip_obj.write(poc_save_path)

                result_zip_obj.close()
                shutil.rmtree(zip_unpacked_path)
                result_zip_file_obj = open(result_zip_path, 'rb')
                result_data = result_zip_file_obj.read()
                result_zip_file_obj.close()

                file_uuid = zip_uuid
                shutil.move(result_zip_path, './static/files/code/' + file_uuid)

                file_data = b''
                if config["files"]["files_storage"] == 'database':
                    f = open('./static/files/code/' + file_uuid, 'rb')
                    file_data = f.read()
                    f.close()
                    remove('./static/files/code/' + file_uuid)

                db.insert_new_file(file_uuid, current_project['id'],
                                   'report_' + curr_time + '.zip', str(int(time.time())),
                                   '{}', 'report', current_user['id'],
                                   storage=config["files"]["files_storage"],
                                   data=file_data)
                clear_report(report_template, report_path)
                return Response(result_data,
                                mimetype="application/zip",
                                headers={
                                    "Content-disposition":
                                        "attachment; filename=report_{}.zip".format(curr_time)})

        else:
            # textfile
            template_file = open(report_path, encoding='utf-8')
            try:
                template_data = template_file.read()
                template_file.close()
                if 'file' in request.files and request.files.get('file').filename and need_to_delete:
                    remove(report_path)

                env = SandboxedEnvironment()
                template_obj = env.from_string(template_data)
                project_dict = db.select_report_info_sorted(
                    current_project['id'])
                rendered_txt = run_function_timeout(template_obj.render, int(config["timeouts"]["report_timeout"]),
                                                    project=project_dict['project'],
                                                    issues=project_dict['issues'],
                                                    hosts=project_dict['hosts'],
                                                    pocs=project_dict['pocs'],
                                                    ports=project_dict['ports'],
                                                    hostnames=project_dict['hostnames'],
                                                    grouped_issues=project_dict['grouped_issues'],
                                                    tasks=project_dict['tasks'],
                                                    notes=project_dict['notes'],
                                                    paths=project_dict['paths'],
                                                    networks=project_dict['networks'],
                                                    credentials=project_dict['credentials'],
                                                    latex_escape=latex_str_escape,
                                                    functions={
                                                        "format_date": lambda unix_time,
                                                                              str_format: datetime.datetime.fromtimestamp(
                                                            int(unix_time)).strftime(str_format),
                                                        "latex_escape": latex_str_escape,
                                                        "ips_in_subnet": lambda ip_arr, network_arr: True in [
                                                            ipaddress.ip_address(ip) in ipaddress.ip_network(network,
                                                                                                             False) for
                                                            ip in ip_arr for network in network_arr],
                                                        "group_issues_by": group_issues_by,
                                                        "csv_escape": csv_escape,
                                                        "issue_targets_list": issue_targets_list
                                                    }
                                                    )
                if rendered_txt:
                    file_uuid = gen_uuid()
                    file_path = './static/files/code/' + file_uuid
                    f = open(file_path, 'w')
                    f.write(rendered_txt)
                    f.close()

                    file_data = b''
                    if config["files"]["files_storage"] == 'database':
                        file_data = rendered_txt.encode('charmap')
                        remove(file_path)

                    db.insert_new_file(file_uuid, current_project['id'],
                                       'report_' + curr_time + '.txt', str(int(time.time())),
                                       '{}', 'report', current_user['id'],
                                       storage=config["files"]["files_storage"],
                                       data=file_data)
                    clear_report(report_template, report_path)
                    return Response(rendered_txt,
                                    mimetype="text/plain",
                                    headers={
                                        "Content-disposition":
                                            "attachment; filename=report_{}.txt".format(curr_time)}
                                    )
                else:
                    errors.append('Template generation timeout!')
                # headers={
                #    "Content-disposition": "attachment; filename=passwords.txt"})
            except Exception as e:
                clear_report(report_template, report_path)
                return render_template(
                    'project/reports/index.html',
                    current_project=current_project,
                    current_user=current_user,
                    errors=errors,
                    exception=str(e),
                    tab_name='Reports')
    clear_report(report_template, report_path)
    return render_template(
        'project/reports/index.html',
        current_project=current_project,
        current_user=current_user,
        errors=errors,
        tab_name='Reports')


@routes.route('/project/<uuid:project_id>/services/edit',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_edit_service_form(project_id, current_project, current_user):
    port = request.args.get('port', '')
    is_tcp = request.args.get('is_tcp', '1')
    service = request.args.get('service', '')
    info = request.args.get('info', '')

    current_service = db.select_ports_by_fields(current_project['id'], port, is_tcp, service, info)

    if not current_service:
        return redirect('/project/{}/services/'.format(current_project['id']))

    return render_template('project/services/edit.html',
                           current_project=current_project,
                           tab_name='Edit service',
                           current_service=current_service)


@routes.route('/project/<uuid:project_id>/services/edit',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_edit_service(project_id, current_project, current_user):
    port = request.args.get('port', '')
    is_tcp = request.args.get('is_tcp', '1')
    service = request.args.get('service', '')
    info = request.args.get('info', '')

    current_service = db.select_ports_by_fields(current_project['id'], port, is_tcp, service, info)

    if not current_service:
        return redirect('/project/{}/services/'.format(current_project['id']))

    ##################################

    form = EditServiceForm()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not errors:
        # validate hosts id
        for host_id in form.host.data:
            current_host = db.select_project_host(current_project['id'], host_id)
            if not current_host:
                errors.append('Host not found!')
                return render_template('project/services/edit.html',
                                       current_project=current_project,
                                       tab_name='Edit service',
                                       current_service=current_service,
                                       errors=errors)
    if not errors:
        # check new port num
        try:
            port = int(form.port.data.split('/')[0])
            is_tcp = 'udp' not in form.port.data.lower()
            if port < 1 or port > 65535:
                errors.append('Port is not in 1..65535')
        except:
            errors.append('Port field parsing error!')

    if not errors:
        # check old port num
        try:
            old_port = int(form.old_port.data.split('/')[0])
            old_is_tcp = 'udp' not in form.old_port.data.lower()
            if old_port < 1 or old_port > 65535:
                errors.append('Old port is not in 1..65535')
        except:
            errors.append('Old port field parsing error!')

    if not errors:
        db.update_service_multiple_info(current_project['id'], old_port, old_is_tcp,
                                        form.old_service.data, form.old_description.data,
                                        port, is_tcp, form.service.data, form.description.data,
                                        form.host.data, current_user['id'])
        url_args = {
            'port': port,
            'is_tcp': str(int(is_tcp)),
            'service': form.service.data,
            'info': form.description.data
        }
        url_get_str = urllib.parse.urlencode(url_args)
        return redirect('/project/{}/services/edit?{}'.format(current_project['id'], url_get_str))

    return render_template('project/services/edit.html',
                           current_project=current_project,
                           tab_name='Edit service',
                           current_service=current_service,
                           errors=errors)


@routes.route('/project/<uuid:project_id>/issue_template/<uuid:template_id>/',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_issue_template_access
@send_log_data
def project_create_issue_from_template(project_id, current_project, current_user, template_id, current_template):
    return render_template('project/issues/from_template.html',
                           current_project=current_project,
                           tab_name='New issue',
                           current_template=current_template)


@routes.route('/project/<uuid:project_id>/issue_template/<uuid:template_id>/',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@check_issue_template_access
@send_log_data
def project_create_issue_from_template_form(project_id, current_project, current_user, template_id, current_template):
    form = NewIssueFromTemplate()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    if not (len(form.variable_value.data) == len(form.variable_type.data) == len(form.variable_name.data)):
        errors.append('Error with variables form!')

    if not errors:
        # add variables
        variables_counter = 0
        add_variables_dict = {}
        for variable_name in form.variable_name.data:
            variable_type = form.variable_type.data[variables_counter]
            variable_value = form.variable_value.data[variables_counter]
            if variable_type in ["text", "number", "float", "boolean"]:
                # add text field
                try:
                    if variable_type == "text":
                        type_func = str
                    elif variable_type == "number":
                        type_func = int
                    elif variable_type == "float":
                        type_func = float
                    elif variable_type == "boolean":
                        type_func = lambda x: bool(int(x))
                    add_variables_dict[variable_name] = {
                        'val': type_func(variable_value) if variable_type == 'text' or variable_value else type_func(0),
                        'type': variable_type
                    }
                except:
                    pass
                variables_counter += 1

        def replace_tpl_text(text: str):
            for variable_name in add_variables_dict:
                variable_type = add_variables_dict[variable_name]['type']
                variable_value = add_variables_dict[variable_name]['val']
                if variable_type == 'boolean':
                    variable_value = int(variable_value)
                text = text.replace('__' + variable_name + '__', str(variable_value))
            return text

        issue_name = replace_tpl_text(current_template['name'])
        issue_description = replace_tpl_text(current_template['description'])
        issue_url_path = replace_tpl_text(current_template['url_path'])
        issue_cvss = current_template['cvss']
        issue_cwe = current_template['cwe']
        issue_cve = replace_tpl_text(current_template['cve'])
        issue_status = replace_tpl_text(current_template['status'])
        issue_type = replace_tpl_text(current_template['type'])
        issue_fix = replace_tpl_text(current_template['fix'])
        issue_param = replace_tpl_text(current_template['param'])

        issue_technical = replace_tpl_text(current_template['technical'])
        issue_risks = replace_tpl_text(current_template['risks'])
        issue_references = replace_tpl_text(current_template['references'])
        issue_intruder = replace_tpl_text(current_template['intruder'])

        issue_fields = json.loads(current_template['fields'])

        for field_name in issue_fields:
            if issue_fields[field_name]['type'] == 'text':
                issue_fields[field_name]['val'] = replace_tpl_text(issue_fields[field_name]['val'])

        issue_fields["pcf_last_used_template"] = {
            "type": "text",
            "val": current_template['id']
        }

        issue_id = db.insert_new_issue(issue_name, issue_description,
                                       issue_url_path, issue_cvss,
                                       current_user['id'], {}, issue_status,
                                       current_project['id'], issue_cve,
                                       issue_cwe, issue_type, issue_fix,
                                       issue_param, issue_fields, issue_technical,
                                       issue_risks, issue_references, issue_intruder)

        return redirect('/project/{}/issue/{}/'.format(current_project['id'], issue_id))

    return render_template('project/issues/from_template.html',
                           current_project=current_project,
                           tab_name='New issue',
                           current_template=current_template,
                           errors=errors)


@routes.route('/project/<uuid:project_id>/hosts/import_hosts', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_hosts_multiple(project_id, current_project, current_user):
    return render_template('project/hosts/multiple.html',
                           current_project=current_project,
                           current_user=current_user,
                           tab_name='New hosts')


@routes.route('/project/<uuid:project_id>/hosts/import_hosts', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_hosts_multiple_form(project_id, current_project, current_user):
    form = MultipleAddHosts()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)

    file_data = ''
    if form.content.data == '' and not form.file.data:
        errors.append("File content does not exist!")
    if form.content.data != '':
        file_data = form.content.data
    if 'file' in request.files and request.files.get('file').filename:
        # if new file
        file = request.files.get('file')
        template_tmp_name = gen_uuid()
        tmp_path = path.join(config['main']['tmp_path'],
                             template_tmp_name)
        file.save(tmp_path)
        file.close()
        file_size = stat(tmp_path).st_size
        if file_size > int(config['files']['template_max_size']):
            remove(tmp_path)
            errors.append('File too large!')
        else:
            f = open(tmp_path)
            file_data = f.read()
            f.close()
            remove(tmp_path)
    if errors:
        return render_template('project/hosts/multiple.html',
                               current_project=current_project,
                               errors=errors,
                               current_user=current_user,
                               tab_name='New hosts')

    # indexes check
    file_lines = file_data.split('\n')
    array_lines = [[y for y in line.strip('\t\r\n').split(form.delimiter.data)] for line in file_lines]
    column_indexes = [
        form.host_num.data,
        form.hostname_num.data,
        form.description_num.data,
        form.os_num.data,
        form.online_num.data,
        form.scope_num.data,
        form.portnum_num.data,
        form.protocol_num.data,
        form.service_num.data,
        form.port_comment_num.data
    ]
    # without 0
    clr_column_indexes = list(filter(lambda a: a > 0, column_indexes))
    if not clr_column_indexes:
        errors.append("No comumn numbers were selected!")
    if len(clr_column_indexes) > len(set(clr_column_indexes)):
        errors.append("Some column indexes are same!")
    if errors:
        return render_template('project/hosts/multiple.html',
                               current_project=current_project,
                               errors=errors,
                               current_user=current_user,
                               tab_name='New hosts')

    if form.do_not_check_columns.data != '1':
        error = 0
        for line in array_lines:
            if max(clr_column_indexes) > len(line):
                error = 1
        if error:
            errors.append("Some rows are incorrect! len(columns) less than index of searching column")

    if errors:
        return render_template('project/hosts/multiple.html',
                               current_project=current_project,
                               errors=errors,
                               current_user=current_user,
                               tab_name='New hosts')
    # prepare for bruteforce

    global_add = 0

    for line in array_lines:
        host = form.host.data
        hostname = form.hostname.data
        description = form.description.data
        os = form.os.data
        online = int('offline' not in form.threats.data)
        scope = int('scope' not in form.threats.data)
        threats = form.threats.data
        if form.host_num.data > 0:
            host = line[form.host_num.data - 1]
        if form.hostname_num.data > 0:
            hostname = line[form.hostname_num.data - 1]
        if form.description_num.data > 0:
            description = line[form.description_num.data - 1]
        if form.os_num.data > 0:
            os = line[form.os_num.data - 1]

        port = form.portnum.data
        protocol = form.protocol.data
        service = form.service.data
        port_comment = form.port_comment.data
        if form.portnum_num.data > 0:
            port = line[form.host_num.data - 1]

        if form.protocol_num.data > 0:
            protocol = line[form.protocol_num.data - 1]

        if form.service_num.data > 0:
            service = line[form.service_num.data - 1]

        if form.port_comment_num.data > 0:
            port_comment = line[form.port_comment_num.data - 1]

        try:
            if form.online_num.data > 0:
                val = int(line[form.online_num.data - 1])
                if not val and 'offline' not in threats:
                    threats.append('offline')
            if form.scope_num.data > 0:
                val = int(line[form.online_num.data - 1])
                if val and 'scope' not in threats:
                    threats.append('scope')
                elif not val and 'noscope' not in threats:
                    threats.append('noscope')
            add = 1
        except ValueError:
            add = 0

        # check ip
        try:
            ipaddress.ip_address(host)
        except:
            add = 0

        # check hostname
        if hostname:
            try:
                email_validator.validate_email_domain_part(hostname)
            except email_validator.EmailNotValidError:
                add = 0

        # check port num
        # if 0 - don't add
        if form.portnum_num.data > 0:
            port = line[form.portnum_num.data - 1]
            try:
                port = int(port)
                if port < 0 or port > 65535:
                    add = 0
            except Exception:
                add = 0

        if protocol and protocol.lower() not in ['tcp', 'udp']:
            add = 0

        if not add:
            global_add += 1
        else:

            if not errors:
                # add host
                host_id = db.select_project_host_by_ip(
                    current_project['id'],
                    host
                )
                if host_id:
                    host_id = host_id[0]['id']
                    db.update_host_comment_threats(host_id,
                                                   description,
                                                   threats,
                                                   os)
                else:
                    host_id = db.insert_host(
                        current_project['id'],
                        host,
                        current_user['id'],
                        description,
                        threats,
                        os
                    )

                # add hostname
                if host_id and hostname:
                    hostname_id = db.select_ip_hostname(host_id, hostname)
                    if hostname_id:
                        hostname_id = hostname_id[0]['id']
                    else:
                        hostname_id = db.insert_hostname(
                            host_id,
                            hostname,
                            '',
                            current_user['id']
                        )
                if host_id and port:
                    port_id = db.select_host_port(host_id, port, protocol.lower() == 'tcp')

                    if port_id:
                        port_id = port_id[0]['id']
                        db.update_port_proto_description(port_id, service, port_comment)
                    else:
                        port_id = db.insert_host_port(host_id, port, protocol.lower() == 'tcp', service,
                                                      port_comment, current_user['id'], current_project['id'])

    if global_add:
        errors.append('{} lines were not added due to format error!'.format(global_add))

    return render_template('project/hosts/multiple.html',
                           current_project=current_project,
                           errors=errors,
                           current_user=current_user,
                           tab_name='New hosts')


@routes.route('/project/<uuid:project_id>/issues/rules', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_issue_rules(project_id, current_project, current_user):
    return render_template('project/issues/rules.html',
                           current_project=current_project,
                           current_user=current_user,
                           tab_name='Use rules',
                           issue_ids=[],
                           rule_ids=[])


@routes.route('/project/<uuid:project_id>/issues/rules.json', methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_issue_rules_json(project_id, current_project, current_user):
    rules_list = db.select_user_all_issue_rules(current_user['id'], current_user['email'])

    rules_json = [{'name': x['name'], 'id': x['id'], 'owner_name': str(x['owner_name'])} for x in rules_list]

    return jsonify(rules_json)


@routes.route('/project/<uuid:project_id>/issues/rules', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_issue_rules_ids(project_id, current_project, current_user):
    form = IssueRuleIDS()

    form.validate()

    return render_template('project/issues/rules.html',
                           current_project=current_project,
                           current_user=current_user,
                           tab_name='Use rules',
                           issue_ids=form.issue_ids.data.split(','),
                           rule_ids=[])


@routes.route('/project/<uuid:project_id>/issues/rules/submit', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def project_issue_rules_form(project_id, current_project, current_user):
    form = RuleUseForm()

    form.validate()
    errors = []

    if form.errors:
        for field in form.errors:
            for error in form.errors[field]:
                errors.append(error)
    if errors:
        return render_template('project/issues/rules.html',
                               current_project=current_project,
                               current_user=current_user,
                               tab_name='Use rules',
                               errors=errors)

    issues_list = form.issues_ids.data.strip(',').split(',')

    rules_list = form.rules_ids.data.strip(',').split(',')

    rules_objs = []

    # check rules UUIDs
    for rule_id in rules_list:
        if not is_valid_uuid(rule_id):
            errors.append('Invalid rule UUID!')
            return render_template('project/issues/rules.html',
                                   current_project=current_project,
                                   current_user=current_user,
                                   tab_name='Use rules',
                                   errors=errors)
    # check rules access:
    rules_obj_list = db.check_user_issue_rules_access(rules_list, current_user['id'], current_user['email'])

    # check issues UUIDs
    for issue_id in issues_list:
        if not is_valid_uuid(issue_id):
            errors.append('Invalid issue UUID!')
            return render_template('project/issues/rules.html',
                                   current_project=current_project,
                                   current_user=current_user,
                                   tab_name='Use rules',
                                   errors=errors)

    # check issues access
    issues_obj_list = db.check_project_issues(issues_list, current_project['id'])

    # 1 - search for issues

    # prepare rules

    for current_rule in rules_obj_list:
        current_rule['search_rules'] = json.loads(current_rule['search_rules'])
        current_rule['extract_vars'] = json.loads(current_rule['extract_vars'])
        current_rule['replace_rules'] = json.loads(current_rule['replace_rules'])

        # fix search rules
        for search_rule in current_rule['search_rules']:
            if search_rule['type'] == 'substring':
                search_rule['val'] = sql_to_regexp(search_rule['val'])

        # fix extract_vars
        for extract_rule in current_rule['extract_vars']:
            if extract_rule['type'] == 'substring':
                extract_rule['val'] = extract_to_regexp(extract_rule['val'])

        # fix replace_rules
        for replace_rule in current_rule['replace_rules']:
            if replace_rule['type'] == 'substring':
                replace_rule['search_filter'] = re.escape(replace_rule['search_filter'])
            elif replace_rule['type'] == 'template':
                pass  # Code moved to next block

        rules_objs.append(current_rule)

    for current_issue in issues_obj_list:
        issue_changed = False
        current_issue['fields'] = json.loads(current_issue['fields'])

        for current_rule in rules_objs:
            # 1 - Search rule
            found = False
            for search_rule in current_rule['search_rules']:
                field_name = search_rule['field_name']
                compare_str = ''
                if field_name == 'name':
                    compare_str = current_issue['name']
                elif field_name == 'description':
                    compare_str = current_issue['description']
                elif field_name == 'fix':
                    compare_str = current_issue['fix']
                elif field_name == 'url':
                    compare_str = current_issue['url_path']
                elif field_name == 'cvss':
                    compare_str = str(current_issue['cvss'])
                elif field_name == 'cve':
                    compare_str = current_issue['cve']
                elif field_name == 'cwe':
                    compare_str = str(current_issue['cwe'])
                elif field_name == 'status':
                    compare_str = current_issue['status']
                elif field_name == 'parameter':
                    compare_str = current_issue['param']
                elif field_name == 'technical':
                    compare_str = current_issue['technical']
                elif field_name == 'risks':
                    compare_str = current_issue['risks']
                elif field_name == 'references':
                    compare_str = current_issue['references']
                elif field_name == 'intruder':
                    compare_str = current_issue['intruder']
                elif field_name == 'criticality':
                    cvss = current_issue['cvss']
                    if cvss == 0:
                        compare_str = 'info'
                    elif cvss <= 3.9:
                        compare_str = 'low'
                    elif cvss <= 6.9:
                        compare_str = 'medium'
                    elif cvss <= 8.9:
                        compare_str = 'high'
                    else:
                        compare_str = 'critical'
                else:
                    # check for additional fields
                    new_name = field_name.strip('_\t\n\r')
                    for issue_field_name in current_issue['fields']:
                        if issue_field_name == new_name and current_issue['fields'][issue_field_name]['type'] != 'file':
                            compare_str = str(current_issue['fields'][issue_field_name]['val'])
                # check
                reg_exp = search_rule['val']
                try:
                    found = bool(run_function_timeout(
                        re.match, int(config["timeouts"]["regexp_timeout"]),
                        pattern=reg_exp,
                        string=compare_str
                    ))
                    # found = bool(re.match(reg_exp, compare_str))
                except Exception as e:
                    found = False

            # 2 - Extract rules
            if found:
                variables_dict = {}
                for extract_rule in current_rule['extract_vars']:
                    field_name = extract_rule['field_name']
                    compare_str = ''
                    if field_name == 'name':
                        compare_str = current_issue['name']
                    elif field_name == 'description':
                        compare_str = current_issue['description']
                    elif field_name == 'fix':
                        compare_str = current_issue['fix']
                    elif field_name == 'url':
                        compare_str = current_issue['url_path']
                    elif field_name == 'cvss':
                        compare_str = str(current_issue['cvss'])
                    elif field_name == 'cve':
                        compare_str = current_issue['cve']
                    elif field_name == 'cwe':
                        compare_str = str(current_issue['cwe'])
                    elif field_name == 'status':
                        compare_str = current_issue['status']
                    elif field_name == 'parameter':
                        compare_str = current_issue['param']
                    elif field_name == 'technical':
                        compare_str = current_issue['technical']
                    elif field_name == 'risks':
                        compare_str = current_issue['risks']
                    elif field_name == 'references':
                        compare_str = current_issue['references']
                    elif field_name == 'intruder':
                        compare_str = current_issue['intruder']
                    elif field_name == 'criticality':
                        cvss = current_issue['cvss']
                        if cvss == 0:
                            compare_str = 'info'
                        elif cvss <= 3.9:
                            compare_str = 'low'
                        elif cvss <= 6.9:
                            compare_str = 'medium'
                        elif cvss <= 8.9:
                            compare_str = 'high'
                        else:
                            compare_str = 'critical'
                    else:
                        # check for additional fields
                        new_name = field_name.strip('_')
                        for issue_field_name in current_issue['fields']:
                            if issue_field_name == new_name and current_issue['fields'][issue_field_name][
                                'type'] != 'file':
                                compare_str = str(current_issue['fields'][issue_field_name]['val'])

                    variable_value = ''
                    try:
                        search_result = run_function_timeout(
                            re.search, int(config["timeouts"]["regexp_timeout"]),
                            pattern=extract_rule['val'],
                            string=compare_str
                        )
                        # search_result = re.search(extract_rule['val'], compare_str)
                        variable_value = str(search_result.group(1))
                    except Exception as e:
                        pass
                    variables_dict[extract_rule['name']] = variable_value

                # 3 - replace rules
                for replace_rule in current_rule['replace_rules']:
                    if replace_rule['type'] != 'template':
                        # replace variables
                        env = SandboxedEnvironment()
                        replace_str = replace_rule["replace_string"]
                        template_obj = env.from_string(replace_str)
                        try:
                            replace_str = run_function_timeout(
                                template_obj.render, int(config["timeouts"]["report_timeout"]),
                                variables_dict,
                                jinja_env=SandboxedEnvironment(autoescape=True)
                            )
                        except Exception as e:
                            pass

                        field_name = replace_rule['field_name']
                        field_original_value = ''
                        found = False
                        special_var = False
                        if field_name in ['name', 'description', 'fix', 'url', 'cvss', 'cve',
                                          'cwe', 'status', 'technical', 'risks', 'references', 'intruder']:
                            field_original_value = current_issue[field_name]
                            found = True
                        elif field_name == 'parameter':
                            field_name = 'param'
                            field_original_value = current_issue[field_name]
                            found = True
                        else:
                            # check for additional fields
                            new_name = field_name.strip('_')
                            for issue_field_name in current_issue['fields']:
                                if issue_field_name == new_name and current_issue['fields'][issue_field_name][
                                    'type'] != 'file':
                                    found = True
                                    field_original_value = str(current_issue['fields'][issue_field_name]['val'])
                                    special_var = True

                        if found:
                            regexp = re.compile(replace_rule['search_filter'])

                            result_string = ''
                            try:
                                result_string = str(run_function_timeout(
                                    regexp.sub, int(config["timeouts"]["regexp_timeout"]),
                                    repl=lambda x: replace_str,
                                    string=field_original_value
                                ))
                                # result_string = str(regexp.sub(lambda x: replace_str, field_original_value))
                            except Exception as e:
                                pass

                            if special_var:
                                # additional field
                                field_type = current_issue['fields'][field_name.strip('_')]['type']
                                try:
                                    if field_type == 'text':
                                        current_issue['fields'][field_name.strip('_')]['val'] = str(result_string)
                                    elif field_type == 'float':
                                        current_issue['fields'][field_name.strip('_')]['val'] = float(result_string)
                                    elif field_type == 'number':
                                        current_issue['fields'][field_name.strip('_')]['val'] = int(result_string)
                                    elif field_type == 'boolean':
                                        current_issue['fields'][field_name.strip('_')]['val'] = bool(result_string)
                                except Exception as e:
                                    pass
                            else:
                                try:
                                    if field_name == 'cvss':
                                        current_issue[field_name] = float(result_string)
                                    elif field_name == 'cwe':
                                        current_issue[field_name] = int(result_string)
                                    else:
                                        current_issue[field_name] = str(result_string)
                                except Exception as e:
                                    pass
                    else:
                        current_template = db.check_user_issue_template_access(replace_rule['id'], current_user['id'],
                                                                               current_user['email'])[0]
                        current_template['variables'] = json.loads(current_template['variables'])
                        replace_rule['template_obj'] = current_template

                        for template_var_name in replace_rule['vars']:
                            var_value = replace_rule['vars'][template_var_name]
                            # replace variables
                            env = SandboxedEnvironment()
                            template_obj = env.from_string(var_value)

                            replace_str = var_value
                            try:
                                replace_str = run_function_timeout(
                                    template_obj.render, int(config["timeouts"]["report_timeout"]),
                                    variables_dict,
                                    jinja_env=SandboxedEnvironment(autoescape=True)
                                )
                                replace_rule['vars'][template_var_name] = replace_str
                            except Exception as e:
                                pass

                        # use template at issue
                        ##########################

                        # replace field variables

                        for field_name in current_template['variables']:
                            if field_name in replace_rule['vars']:
                                try:
                                    if current_template['variables'][field_name]["type"] == "boolean":
                                        current_template['variables'][field_name]["val"] = bool(
                                            replace_rule['vars'][field_name])
                                    elif current_template['variables'][field_name]["type"] == "number":
                                        current_template['variables'][field_name]["val"] = int(
                                            replace_rule['vars'][field_name])
                                    elif current_template['variables'][field_name]["type"] == "float":
                                        current_template['variables'][field_name]["val"] = float(
                                            replace_rule['vars'][field_name])
                                    elif current_template['variables'][field_name]["type"] == "text":
                                        current_template['variables'][field_name]["val"] = str(
                                            replace_rule['vars'][field_name])
                                except Exception as e:
                                    pass
                        add_variables_dict = current_template['variables']

                        def replace_tpl_text(text: str):
                            for variable_name in add_variables_dict:
                                variable_type = add_variables_dict[variable_name]['type']
                                variable_value = add_variables_dict[variable_name]['val']
                                if variable_type == 'boolean':
                                    variable_value = int(variable_value)
                                text = text.replace('__' + variable_name + '__', str(variable_value))
                            return text

                        issue_name = replace_tpl_text(current_template['name'])
                        issue_description = replace_tpl_text(current_template['description'])
                        issue_url_path = replace_tpl_text(current_template['url_path'])
                        issue_cvss = current_template['cvss']
                        issue_cwe = current_template['cwe']
                        issue_cve = replace_tpl_text(current_template['cve'])
                        issue_status = replace_tpl_text(current_template['status'])
                        issue_type = replace_tpl_text(current_template['type'])
                        issue_fix = replace_tpl_text(current_template['fix'])
                        issue_param = replace_tpl_text(current_template['param'])
                        issue_technical = replace_tpl_text(current_template['technical'])
                        issue_risks = replace_tpl_text(current_template['risks'])
                        issue_references = replace_tpl_text(current_template['references'])
                        issue_intruder = replace_tpl_text(current_template['intruder'])

                        issue_fields = json.loads(current_template['fields'])

                        for field_name in issue_fields:
                            if issue_fields[field_name]['type'] == 'text':
                                issue_fields[field_name]['val'] = replace_tpl_text(issue_fields[field_name]['val'])

                        current_issue = {
                            'id': current_issue['id'],
                            'name': issue_name,
                            'description': issue_description,
                            'url_path': issue_url_path,
                            'cvss': float(issue_cvss),
                            'cwe': int(issue_cwe),
                            'cve': issue_cve,
                            'user_id': current_issue['user_id'],
                            'services': current_issue['services'],
                            'status': issue_status,
                            'project_id': current_issue['project_id'],
                            'type': issue_type,
                            'fix': issue_fix,
                            'param': issue_param,
                            'fields': issue_fields,
                            'technical': issue_technical,
                            'risks': issue_risks,
                            'references': issue_references,
                            'intruder': issue_intruder
                        }
                # submit issue
                db.update_issue_with_fields(current_issue['id'], current_issue['name'], current_issue['description'],
                                            current_issue['url_path'], current_issue['cvss'],
                                            json.loads(current_issue['services']),
                                            current_issue['status'], current_issue['cve'], current_issue['cwe'],
                                            current_issue['fix'],
                                            current_issue['type'], current_issue['param'], current_issue['fields'],
                                            current_issue['technical'], current_issue['risks'],
                                            current_issue['references'], current_issue['intruder'])

    return render_template('project/issues/rules.html',
                           current_project=current_project,
                           current_user=current_user,
                           tab_name='Use rules',
                           issue_ids=form.issues_ids.data.split(','),
                           rule_ids=form.rules_ids.data.split(','))


@routes.route('/project/<uuid:project_id>/new_task', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def new_task_form(project_id, current_project, current_user):
    form = AddNewTask()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if errors:
        return jsonify({'errors': errors})

    # check users & teams

    user_ids = [x['id'] for x in db.select_project_users(current_project['id'])]

    team_ids = json.loads(current_project['teams'])

    for user_id in json.loads(form.users.data):
        if user_id not in user_ids:
            errors.append('One of users was not found!')

    for team_id in json.loads(form.teams.data):
        if team_id not in team_ids:
            errors.append('One of teams was not found!')

    user_ids = json.loads(form.users.data)
    team_ids = json.loads(form.teams.data)

    if errors:
        return jsonify({'errors': errors})

    hosts_json = {}

    # { port_id: ["0", hostname_id], ... }

    # check hosts
    for host_str in json.loads(form.hosts.data):
        port_id = host_str.split(':')[0]
        hostname_id = host_str.split(':')[1]
        current_port = db.select_project_port(current_project['id'], port_id)
        if not current_port:
            return jsonify({'errors': ["Port was not found!"]})
        current_port = current_port[0]
        if hostname_id != "0":
            current_hostname = db.select_project_hostname(current_project['id'], hostname_id)
            if not current_hostname or current_hostname[0]["host_id"] != current_port['host_id']:
                return jsonify({'errors': ["Hostname was not found!"]})

        if port_id not in hosts_json:
            hosts_json[port_id] = []
        if hostname_id not in hosts_json[port_id]:
            hosts_json[port_id].append(hostname_id)

    if not errors:
        task_id = db.insert_new_task(form.name.data, form.description.data, form.criticality.data,
                                     team_ids, user_ids, form.status.data, form.start_date.data,
                                     form.end_date.data, current_project['id'], hosts_json)
        if task_id:
            return jsonify({'status': 'ok'})

    return jsonify({'errors': errors})


@routes.route('/project/<uuid:project_id>/move_task', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def move_task_form(project_id, current_project, current_user):
    form = MoveTask()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if errors:
        return jsonify({'errors': errors})

    current_task = db.select_task(str(form.task_id.data), current_project['id'])
    if not current_task:
        return jsonify({'errors': ["Task was not found!"]})

    current_task = current_task[0]

    if form.status.data != current_task['status']:
        db.update_task_status(current_task['id'], form.status.data)

    return jsonify({'status': "ok"})


@routes.route('/project/<uuid:project_id>/delete_task', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def delete_task_form(project_id, current_project, current_user):
    form = DeleteTask()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if errors:
        return jsonify({'errors': errors})

    current_task = db.select_task(str(form.task_id.data), current_project['id'])
    if not current_task:
        return jsonify({'errors': ["Task was not found!"]})

    current_task = current_task[0]

    db.delete_task(current_task['id'])

    return jsonify({'status': "ok"})


@routes.route('/project/<uuid:project_id>/edit_task', methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def edit_task_form(project_id, current_project, current_user):
    form = EditTask()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if errors:
        return jsonify({'errors': errors})

    # check task
    current_task = db.select_task(form.task_id.data, current_project['id'])
    if not current_task:
        return jsonify({'errors': "Task was not found!"})
    current_task = current_task[0]

    # check users & teams

    user_ids = [x['id'] for x in db.select_project_users(current_project['id'])]

    team_ids = json.loads(current_project['teams'])

    for user_id in json.loads(form.users.data):
        if user_id not in user_ids:
            errors.append('One of users was not found!')

    for team_id in json.loads(form.teams.data):
        if team_id not in team_ids:
            errors.append('One of teams was not found!')

    user_ids = json.loads(form.users.data)
    team_ids = json.loads(form.teams.data)

    if errors:
        return jsonify({'errors': errors})

    hosts_json = {}

    # { port_id: ["0", hostname_id], ... }

    # check hosts
    for host_str in json.loads(form.hosts.data):
        port_id = host_str.split(':')[0]
        hostname_id = host_str.split(':')[1]
        current_port = db.select_project_port(current_project['id'], port_id)
        if not current_port:
            return jsonify({'errors': ["Port was not found!"]})
        current_port = current_port[0]
        if hostname_id != "0":
            current_hostname = db.select_project_hostname(current_project['id'], hostname_id)
            if not current_hostname or current_hostname[0]["host_id"] != current_port['host_id']:
                return jsonify({'errors': ["Hostname was not found!"]})

        if port_id not in hosts_json:
            hosts_json[port_id] = []
        if hostname_id not in hosts_json[port_id]:
            hosts_json[port_id].append(hostname_id)

    if not errors:
        db.update_task(form.name.data, form.description.data, form.criticality.data,
                       team_ids, user_ids, form.status.data, form.start_date.data,
                       form.end_date.data, hosts_json, current_task['id'])

        return jsonify({'status': 'ok'})
    return jsonify({'errors': errors})


@routes.route('/project/<uuid:project_id>/todo/export_json',
              methods=['GET'])
@requires_authorization
@check_session
@check_project_access
@send_log_data
def todo_export_tasks_json(project_id, current_project, current_user):
    tasks = db.select_project_tasks(current_project['id'])

    tasks_arr = []

    for task_obj in tasks:
        tmp_obj = {
            'name': task_obj['name'],
            'description': task_obj['description'],
            'start_date': task_obj['start_date'],
            'finish_date': task_obj['finish_date'],
            'status': task_obj['status'],
            'criticality': task_obj['criticality'],
            'teams': [],
            'users': [],
            'services': {"ids": {}, "names": []}
        }

        # add users
        for obj_user_id in json.loads(task_obj['users']):
            selected_user = db.select_user_by_id(obj_user_id)[0]
            tmp_obj['users'].append(
                {
                    'id': obj_user_id,
                    'email': selected_user['email']
                }
            )

        # add teams

        for obj_team_id in json.loads(task_obj['teams']):
            selected_team = db.select_team_by_id(obj_team_id)[0]
            tmp_obj['teams'].append(
                {
                    'id': obj_team_id,
                    'name': selected_team['name']
                }
            )

        # add services
        tmp_obj['services']['ids'] = json.loads(task_obj['services'])
        for port_id in json.loads(task_obj['services']):

            port = db.select_port(port_id)[0]
            host = db.select_host_by_port_id(port_id)[0]

            hostnames_id_list = json.loads(task_obj['services'])[port_id]

            for hostname_id in hostnames_id_list:
                if hostname_id == '0':
                    tmp_obj['services']['names'].append(
                        {
                            'ip': host['ip'],
                            'hostname': '',
                            'port': port['port'],
                            'is_tcp': bool(port['is_tcp'])
                        }
                    )
                else:
                    hostname_obj = db.select_hostname(hostname_id)[0]
                    tmp_obj['services']['names'].append(
                        {
                            'ip': host['ip'],
                            'hostname': hostname_obj['hostname'],
                            'port': port['port'],
                            'is_tcp': bool(port['is_tcp'])
                        }
                    )
        tasks_arr.append(tmp_obj)
    return Response(
        json.dumps(tasks_arr),
        mimetype='text/plain',
        headers={'Content-disposition': 'attachment; filename=pcf_tasks.json'})


@routes.route('/project/<uuid:project_id>/todo/import_json',
              methods=['POST'])
@requires_authorization
@check_session
@check_project_access
@check_project_archived
@send_log_data
def todo_import_tasks_form(project_id, current_project, current_user):
    form = TODOImportJSONForm()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    if errors:
        return redirect('/project/{}/?error=One+of+files+was+wrong!'.format(current_project['id']))

    for file in form.json_files.data:
        if file.filename:
            file_content = file.read().decode('charmap')
            try:
                file_dict = json.loads(file_content)
                for task_obj in file_dict:
                    task_name = str(task_obj['name']) if str(task_obj['name']) else "task name"
                    task_description = str(task_obj['description'])
                    task_start_date = int(task_obj['start_date'])
                    task_finish_date = int(task_obj['finish_date'])
                    task_status = str(task_obj['status']) if str(task_obj['status']) in ["todo", "progress", "review",
                                                                                         "done"] else "todo"
                    task_criticality = str(task_obj['criticality']) if str(task_obj['criticality']) in ["critical",
                                                                                                        "high",
                                                                                                        "medium", "low",
                                                                                                        "info"] else "info"

                    # get_users
                    project_users = db.select_project_users(current_project['id'])

                    task_users = []

                    for user_obj in list(task_obj['users']):
                        add_user_id = str(user_obj['id']) if user_obj['id'] and check_uuid(str(user_obj['id'])) else ''
                        add_user_email = str(user_obj['email'])
                        if add_user_id:
                            real_user = db.select_user_by_id(add_user_id)
                            if not real_user:
                                real_user = db.select_user_by_email(add_user_email)
                            if real_user:
                                real_user = real_user[0]
                                for exited_user in project_users:
                                    if exited_user['id'] == real_user['id']:
                                        task_users.append(real_user['id'])
                    task_users = list(set(task_users))

                    # get teams
                    project_teams = db.select_project_teams(current_project['id'])

                    task_teams = []
                    for team_obj in list(task_obj['teams']):
                        add_team_id = str(team_obj['id']) if team_obj['id'] and check_uuid(str(team_obj['id'])) else ''
                        add_team_name = str(team_obj['name'])
                        if add_team_id:
                            real_team = db.select_team_by_id(add_team_id)
                            if real_team:
                                real_team = real_team[0]
                                for exited_team in project_teams:
                                    if exited_team['id'] == real_team['id']:
                                        task_teams.append(exited_team['id'])
                            elif add_team_name:
                                counter = 0
                                real_team_id = ''
                                for exited_team in project_teams:
                                    if exited_team['name'] == add_team_name:
                                        counter += 1
                                        real_team_id = exited_team['id']
                                if counter == 1:
                                    task_teams.append(real_team_id)
                    task_teams = list(set(task_teams))

                    # add services
                    task_services = {}

                    def add_service(port_id: str, hostname_id: str):
                        if port_id not in task_services:
                            task_services[port_id] = []
                            if hostname_id not in task_services[port_id]:
                                task_services[port_id].append(hostname_id)

                    for add_port_id in task_obj['services']['ids']:
                        real_port = db.select_project_port(current_project['id'], str(add_port_id))
                        if real_port:
                            real_port = real_port[0]
                            hostnames_list = task_obj['services']['ids'][add_port_id]
                            for hostname_id in hostnames_list:
                                if hostname_id == "0":
                                    add_service(real_port['id'], "0")
                                else:
                                    real_hostname = db.select_hostname_with_host_id(real_port['host_id'],
                                                                                    str(hostname_id))
                                    if real_hostname:
                                        real_hostname = real_hostname[0]
                                        add_service(real_port['id'], real_hostname)
                    for add_port_obj in task_obj['services']['names']:
                        try:
                            ipaddress.ip_address(add_port_obj['ip'])
                            ip = str(add_port_obj['ip'])
                            real_host = db.select_project_host_by_ip(current_project['id'], ip)
                            if real_host:
                                real_host = real_host[0]
                                add_port_num = int(add_port_obj['port'])
                                add_port_is_tcp = bool(add_port_obj['is_tcp'])
                                real_port = db.select_host_port(real_host['id'], add_port_num, add_port_is_tcp)
                                if real_port:
                                    real_port = real_port[0]
                                    hostname = str(add_port_obj['hostname'])
                                    if hostname == "0":
                                        add_service(real_port['id'], "0")
                                    else:
                                        real_hostname = db.select_ip_hostname(real_host['id'], str(hostname))
                                        if real_hostname:
                                            real_hostname = real_hostname[0]
                                            add_service(real_port['id'], real_hostname['id'])
                        except Exception as e1:
                            print(e1)

                    todo_id = db.insert_new_task(task_name, task_description, task_criticality, task_teams,
                                                 task_users, task_status, task_start_date, task_finish_date,
                                                 current_project['id'], task_services)

            except Exception as e:
                print(e)
                return redirect('/project/{}/?error=One+of+files+was+wrong!'.format(current_project['id']))
    return redirect('/project/{}/'.format(current_project['id']))
