from app import session, render_template, redirect, request, \
    requires_authorization, cache
from flask import send_from_directory
import json
from os import stat, remove
import calendar
from urllib.parse import urlparse
import urllib.parse

from system.crypto_functions import check_hash, gen_uuid

from system.forms import *

from routes.ui import routes

from app import check_session, check_team_access, db, send_log_data, \
    config


@cache.cached(timeout=120)
@routes.route('/static/files/code/<uuid:file_id>')
def getStaticCodeFile(file_id):
    return send_from_directory('static/files/code', str(file_id),
                               as_attachment=True,
                               attachment_filename=
                               db.select_files(str(file_id))[0]['filename'])


@cache.cached(timeout=120)
@routes.route('/static/files/poc/<uuid:poc_id>')
def getStaticPoCFile(poc_id):
    return send_from_directory('static/files/poc', str(poc_id),
                               as_attachment=True,
                               attachment_filename=
                               db.select_poc(str(poc_id))[0]['filename'])


@cache.cached(timeout=120)
@routes.route('/static/files/templates/<uuid:template_id>')
def getStaticTemplateFile(template_id):
    return send_from_directory('static/files/templates', str(template_id),
                               as_attachment=True,
                               attachment_filename=
                               db.select_templates(
                                   template_id=str(template_id))[0]['filename'])


@cache.cached(timeout=120)
@routes.route('/static/<path:path>')
def getStaticFile(path):
    return send_from_directory('static', path, as_attachment=True)


@routes.route('/')
@requires_authorization
def index():
    return render_template('index.html')


@routes.route('/login', methods=['GET'])
@requires_authorization
def login():
    if session.get('id'):
        return redirect('/projects/')
    return render_template('login.html',
                           tab_name='Login')


@routes.route('/login', methods=['POST'])
@requires_authorization
def login_form():
    form = LoginForm()
    error = None
    if form.validate():
        try:
            data = db.select_user_by_email(form.email.data)[0]
        except IndexError:
            data = []
        if not data:
            error = 'Email does not exist!'
        else:
            if not check_hash(data['password'], form.password.data):
                error = 'Wrong password!'
            else:
                session.update(data)
        if not error:
            if request.args.get('redirect') is not None:
                return redirect(urlparse(request.args.get('redirect')).path)
            return redirect('/projects/')
    return render_template('login.html', form=form, error=error,
                           tab_name='Login')


@routes.route('/register', methods=['GET'])
@requires_authorization
def register():
    return render_template('register.html',
                           tab_name='Register')


@routes.route('/register', methods=['POST'])
@requires_authorization
def register_form():
    form = RegistrationForm()
    error = None
    if form.validate():
        if len(db.select_user_by_email(form.email.data)) > 0:
            error = 'Email already exist!'
        else:
            db.insert_user(form.email.data, form.password1.data)
    return render_template('register.html', form=form, error=error,
                           tab_name='Register')


@routes.route('/profile', methods=['GET'])
@requires_authorization
@check_session
@send_log_data
def profile(current_user):
    return render_template('profile.html', user_data=current_user,
                           tab_name='Profile')


@routes.route('/profile', methods=['POST'])
@requires_authorization
@check_session
@send_log_data
def profile_form(current_user):
    form1 = ChangeProfileInfo()
    form2 = ChangeProfilePassword()
    add_config_form = AddConfig()
    add_report_form = AddReportTemplate()
    delete_report_form = DeleteReportTemplate()

    errors = []
    success_message = ''
    error_type = ''
    success_type = ''

    # editing profile data
    if 'change_profile' in request.form:
        form1.validate()
        if form1.errors:
            for field in form1.errors:
                errors += form1.errors[field]
            error_type = 'change_profile'
        if not errors:
            # check email
            find_user = db.select_user_by_email(form1.email.data)
            if find_user and find_user[0]['id'] != session['id']:
                errors.append('Email connected to another user!')
                error_type = 'change_profile'

        if not errors:
            if not check_hash(current_user['password'], form1.password.data):
                errors.append('Wrong password!')
                error_type = 'change_profile'
            else:
                db.update_user_info(session['id'],
                                    fname=form1.fname.data,
                                    lname=form1.lname.data,
                                    email=form1.email.data,
                                    company=form1.company.data)
                success_message = 'Profile information was updated!'
                success_type = 'change_profile'

    # editing profile password
    elif 'change_password' in request.form:
        form2.validate()
        if form2.errors:
            for field in form2.errors:
                errors += form2.errors[field]
            error_type = 'change_password'
        else:
            if form2.oldpassword.data == form2.password1.data:
                errors.append('New password is equal to old!')
                error_type = 'change_password'
            else:
                if not check_hash(current_user['password'],
                                  form2.oldpassword.data):
                    errors.append('Wrong password!')
                    error_type = 'change_password'
                else:
                    db.update_user_password(current_user['id'],
                                            form2.password1.data)
                    success_message = 'Password was updated!'
                    success_type = 'change_password'
    elif 'add_config' in request.form:
        add_config_form.validate()
        if add_config_form.errors:
            for field in add_config_form.errors:
                errors += add_config_form.errors[field]
            error_type = 'add_config'
        else:
            if add_config_form.action.data == 'Add':
                display_name = ''
                config_name = add_config_form.config_name.data
                visible = 0
                if config_name == 'shodan':
                    display_name = 'Shodan API key'
                    visible = 0

                if config_name == 'zeneye':
                    display_name = 'Zeneye API key'
                    visible = 0

                # check if exist
                same_config = db.select_configs(user_id=current_user['id'],
                                                name=config_name)
                if same_config:
                    db.update_config(user_id=current_user['id'],
                                     name=config_name,
                                     value=add_config_form.config_value.data)
                else:
                    config_id = db.insert_config(user_id=current_user['id'],
                                                 name=config_name,
                                                 display_name=display_name,
                                                 data=add_config_form.config_value.data,
                                                 visible=0)
            elif add_config_form.action.data == 'Delete':
                db.delete_config(user_id=current_user['id'],
                                 name=add_config_form.config_name.data)
    elif 'add_template' in request.form:
        add_report_form.validate()
        errors = []
        if add_report_form.errors:
            for field in add_report_form.errors:
                errors += add_report_form.errors[field]
            error_type = 'add_template'
        else:
            template_id = gen_uuid()
            file = request.files.get('file')
            tmp_file_path = './static/files/templates/{}'.format(template_id)
            file.save(tmp_file_path)
            file.close()
            file_size = stat(tmp_file_path).st_size
            if file_size > int(config['files']['template_max_size']):
                errors.append("File too large!")
                remove(tmp_file_path)
                error_type = 'add_template'
            else:
                template_id = db.insert_template(user_id=current_user['id'],
                                                 name=add_report_form.template_name.data,
                                                 template_id=template_id,
                                                 filename=file.filename
                                                 )
    elif 'delete_template' in request.form:
        delete_report_form.validate()
        errors = []
        if delete_report_form.errors:
            for field in delete_report_form.errors:
                errors += delete_report_form.errors[field]
            error_type = 'delete_template'
        else:
            template_id = delete_report_form.template_id.data
            current_template = db.select_templates(template_id=template_id,
                                                   user_id=current_user['id'])
            if not current_template:
                errors.append('Template not found!')
                error_type = 'delete_template'
            else:
                current_template = current_template[0]
                db.delete_template_safe(template_id=current_template['id'],
                                        user_id=current_user['id'])

    current_user = db.select_user_by_id(session['id'])[0]
    return render_template('profile.html', user_data=current_user,
                           success_message=success_message, errors=errors,
                           tab_name='Profile', error_type=error_type,
                           success_type=success_type)


@routes.route('/logout')
@requires_authorization
def logout():
    try:
        del session['id']
    except:
        pass
    if 'redirect' in request.args and request.args.get('redirect'):
        return redirect('/login?redirect={}'.format(
            urllib.parse.quote(request.args.get('redirect'))))
    return redirect('/login')


@routes.route('/create_team', methods=['GET'])
@requires_authorization
@check_session
@send_log_data
def create_team(current_user):
    return render_template('new_team.html',
                           tab_name='Create team')


@routes.route('/create_team', methods=['POST'])
@requires_authorization
@check_session
@send_log_data
def create_team_form(current_user):
    form = CreateNewTeam()
    form.validate()
    errors = []
    success_message = ''

    if form.errors:
        for field in form.errors:
            errors += form.errors[field]
    else:
        team_id = db.insert_team(form.name.data, form.description.data, session['id'])
        success_message = 'New team was created!'
        return redirect ('/team/{}/'.format(team_id))
    return render_template('new_team.html',
                           tab_name='Create team', errors=errors, success_message=success_message)


@routes.route('/team/<uuid:team_id>/', methods=['GET'])
@requires_authorization
@check_session
@check_team_access
@send_log_data
def team_page(team_id, current_team, current_user):
    edit_error = request.args.get('edit_error', default='', type=str)

    return render_template('team.html', current_team=current_team,
                           edit_error=edit_error,
                           tab_name=current_team['name'] if current_team['name'] else 'Team info')


@routes.route('/team/<uuid:team_id>/', methods=['POST'])
@requires_authorization
@check_session
@check_team_access
@send_log_data
def team_page_form(team_id, current_team, current_user):
    current_team_users = json.loads(current_team['users'])

    if current_team_users[current_user['id']] != 'admin':
        return render_template('team.html', current_team=current_team,
                               tab_name=current_team['name'] if current_team['name'] else 'Team info')

    # forms list

    team_info_form = EditTeamInfo()
    team_info_form.validate()
    team_user_add_form = AddUserToProject()
    team_user_add_form.validate()
    add_config_form = AddConfig()
    add_config_form.validate()
    add_report_form = AddReportTemplate()
    add_report_form.validate()
    delete_report_form = DeleteReportTemplate()
    delete_report_form.validate()

    errors = []
    # team info edit
    if 'change_info' in request.form:
        if team_info_form.errors:
            for field in team_info_form.errors:
                errors += team_info_form.errors[field]
            current_team = db.select_team_by_id(str(team_id))[0]
            return render_template('team.html', current_team=current_team,
                                   team_info_errors=errors,
                                   tab_name=current_team['name'] if current_team['name'] else 'Team info')
        if team_info_form.action.data == 'Save':
            db.update_team_info(str(team_id),
                                team_info_form.name.data,
                                team_info_form.email.data,
                                team_info_form.description.data, current_user['id'])
            current_team = db.select_team_by_id(str(team_id))[0]
            return render_template('team.html', current_team=current_team,
                                   tab_name=current_team['name'] if current_team['name'] else 'Team info',
                                   team_info_errors=[])
        elif team_info_form.action.data == 'Delete':
            db.delete_team_safe(current_team['id'])
            return redirect('/create_team')

    # team tester add
    elif 'add_user' in request.form:
        errors = []
        if team_user_add_form.errors:
            for field in team_user_add_form.errors:
                errors += team_user_add_form.errors[field]

        else:
            user_to_add = db.select_user_by_email(team_user_add_form.email.data)
            if not user_to_add:
                errors = ['User does not found!']
            elif user_to_add[0]['id'] in current_team_users:
                errors = ['User already added to {} group!'.format(
                    current_team_users[user_to_add[0]['id']])]
            else:
                db.update_new_team_user(current_team['id'],
                                        team_user_add_form.email.data,
                                        team_user_add_form.role.data)

        current_team = db.select_team_by_id(str(team_id))[0]
        if team_user_add_form.role.data == 'tester':
            return render_template('team.html', current_team=current_team,
                                   add_tester_errors=errors,
                                   tab_name=current_team['name'] if current_team['name'] else 'Team info')
        else:
            return render_template('team.html', current_team=current_team,
                                   add_admin_errors=errors,
                                   tab_name=current_team['name'] if current_team['name'] else 'Team info')

    elif 'add_config' in request.form:
        errors = []
        if add_config_form.errors:
            for field in add_config_form.errors:
                errors += add_config_form.errors[field]
        else:
            if add_config_form.action.data == 'Add':
                display_name = ''
                config_name = add_config_form.config_name.data
                visible = 0
                if config_name == 'shodan':
                    display_name = 'Shodan API key'
                    visible = 0

                if config_name == 'zeneye':
                    display_name = 'Zeneye API key'
                    visible = 0

                # check if exist
                same_config = db.select_configs(team_id=current_team['id'],
                                                name=config_name)
                if same_config:
                    db.update_config(team_id=current_team['id'],
                                     name=config_name,
                                     value=add_config_form.config_value.data)
                else:
                    config_id = db.insert_config(user_id='0',
                                                 team_id=current_team['id'],
                                                 name=config_name,
                                                 display_name=display_name,
                                                 data=add_config_form.config_value.data,
                                                 visible=0)
            elif add_config_form.action.data == 'Delete':
                db.delete_config(team_id=current_team['id'],
                                 user_id='0',
                                 name=add_config_form.config_name.data)
        return render_template('team.html', current_team=current_team,
                               add_config_errors=errors,
                               tab_name=current_team['name'] if current_team['name'] else 'Team info')
    elif 'add_template' in request.form:
        errors = []
        if add_report_form.errors:
            for field in add_report_form.errors:
                errors += add_report_form.errors[field]
        else:
            template_id = gen_uuid()
            file = request.files.get('file')
            tmp_file_path = './static/files/templates/{}'.format(template_id)
            file.save(tmp_file_path)
            file.close()
            file_size = stat(tmp_file_path).st_size
            if file_size > int(config['files']['template_max_size']):
                errors.append("File too large!")
                remove(tmp_file_path)
            else:
                template_id = db.insert_template(team_id=current_team['id'],
                                                 name=add_report_form.template_name.data,
                                                 template_id=template_id,
                                                 filename=file.filename
                                                 )
        return render_template('team.html', current_team=current_team,
                               add_report_errors=errors,
                               tab_name=current_team['name'] if current_team['name'] else 'Team info')
    elif 'delete_template' in request.form:
        errors = []
        if delete_report_form.errors:
            for field in delete_report_form.errors:
                errors += delete_report_form.errors[field]
        else:
            template_id = delete_report_form.template_id.data
            current_template = db.select_templates(template_id=template_id, team_id=current_team['id'])
            if not current_template:
                errors.append('Template not found!')
            else:
                current_template = current_template[0]
                db.delete_template_safe(template_id=current_template['id'],
                                        team_id=current_team['id'])
        return render_template('team.html', current_team=current_team,
                               add_report_errors=errors,
                               tab_name=current_team['name'] if current_team['name'] else 'Team info')


@routes.route('/new_project', methods=['GET'])
@requires_authorization
@check_session
@send_log_data
def new_project(current_user):
    team_id = request.args.get('team_id', default='', type=str)
    if team_id != '':
        # team access check
        user_teams = db.select_user_teams(session['id'])
        current_team = {}
        for found_team in user_teams:
            if found_team['id'] == str(team_id):
                current_team = found_team
        if current_team == {}:
            return redirect('/projects/new_project')

    return render_template('new_project.html', team_id=team_id,
                           tab_name='New project')


@routes.route('/new_project', methods=['POST'])
@requires_authorization
@check_session
@send_log_data
def new_project_form(current_user):
    # team access check
    form = AddNewProject()
    form.validate()
    errors = []
    if form.errors:
        for field in form.errors:
            for err in form.errors[field]:
                errors.append(err)
        return render_template('new_project.html', errors=errors,
                               tab_name='New project')

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

    if errors:
        return render_template('new_project.html', errors=errors,
                               tab_name='New project')

    # creating project
    start_time = calendar.timegm(form.start_date.data.timetuple())
    end_time = calendar.timegm(form.end_date.data.timetuple())

    if current_user['id'] not in form_users:
        form_users.append(current_user['id'])

    project_id = db.insert_new_project(form.name.data,
                                       form.description.data,
                                       form.project_type.data,
                                       form.scope.data,
                                       start_time,
                                       end_time,
                                       form.archive.data,
                                       form_users,
                                       form.teams.data,
                                       session['id'],
                                       current_user['id'])

    return redirect('/project/{}/'.format(project_id))


@routes.route('/team/<uuid:team_id>/user/<uuid:user_id>/<action>',
              methods=['POST'])
@requires_authorization
@check_session
@check_team_access
@send_log_data
def team_user_edit(team_id, user_id, action, current_team, current_user):
    # check if user admin
    if not db.check_admin_team(str(team_id), session['id']):
        return redirect('/create_team')

    error = ''

    if action == 'kick':
        error = db.delete_user_from_team(str(team_id), str(user_id),
                                         current_user['id'])

    if action == 'devote':
        error = db.devote_user_from_team(str(team_id), str(user_id),
                                         current_user['id'])

    if action == 'set_admin':
        error = db.set_admin_team_user(str(team_id), str(user_id),
                                       current_user['id'])

    return redirect('/team/{}/?edit_error={}#/users'.format(str(team_id), error))


@routes.route('/profile/<uuid:user_id>/', methods=['GET'])
@requires_authorization
@check_session
def user_profile(user_id, current_user):
    # TODO: fix
    user_data = db.select_user_by_id(str(user_id))
    if not user_data:
        return redirect('/profile')
    user_data = user_data[0]
    return render_template('profile_noname.html', user_data=user_data,
                           tab_name='User: {}'.format(user_data['email']))


@routes.route('/projects/', methods=['GET'])
@requires_authorization
@check_session
def list_projects(current_user):
    return render_template('projects.html',
                           tab_name='Projects')
