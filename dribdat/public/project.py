# -*- coding: utf-8 -*-
"""Views related to project management."""
from flask import (
    Blueprint, request, render_template, flash, url_for, redirect
)
from flask_login import login_required, current_user
from dribdat.user.models import Event, Project, Activity, User
from dribdat.database import db
from dribdat.extensions import cache
from dribdat.public.forms import (
    ProjectNew, ProjectPost, ProjectBoost, ProjectComment
)
from dribdat.aggregation import (
    SyncProjectData, GetProjectData, IsProjectStarred
)
from dribdat.user import (
    validateProjectData, projectProgressList, isUserActive,
)
from dribdat.public.projhelper import (
    project_action, project_edit_action, resources_by_stage
)
from ..decorators import admin_required

blueprint = Blueprint('project', __name__,
                      static_folder="../static", url_prefix='/project')


@blueprint.route('/<int:project_id>/')
@blueprint.route('/<int:project_id>')
def project_view(project_id):
    """Show a project by id."""
    return project_action(project_id, None)


@blueprint.route('/<int:project_id>/log')
def project_view_posted(project_id):
    """Identical to the above."""
    return redirect(url_for(
        'project.project_view', project_id=project_id) + '#log')


@blueprint.route('/s/<project_name>')
def project_view_name(project_name):
    """Show a project matching by name."""
    project = Project.query.filter(
                Project.name.ilike(project_name)).first_or_404()
    return project_view(project.id)


@blueprint.route('/<int:project_id>/edit', methods=['GET', 'POST'])
@login_required
def project_edit(project_id):
    """Edit a project."""
    return project_edit_action(project_id)


@blueprint.route('/<int:project_id>/details', methods=['GET', 'POST'])
@login_required
def project_details(project_id):
    """Edit a project's details."""
    return project_edit_action(project_id, True)


@blueprint.route('/<int:project_id>/boost', methods=['GET', 'POST'])
@login_required
@admin_required
def project_boost(project_id):
    """Add a booster to a project."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    event = project.event

    form = ProjectBoost(obj=project, next=request.args.get('next'))

    # TODO: load from a YAML file or from the Presets config
    form.boost_type.choices = [
        '---',
        'Awesome sauce',
        'Data wizards',
        'Glorious purpose',
        'Top tutorial',
        'Super committers',
    ]

    # Process form
    if form.validate_on_submit():
        # Update project data
        cache.clear()
        project_action(project_id, 'boost',
                       action=form.boost_type.data, text=form.note.data)
        flash('Thanks for your boost!', 'success')
        return project_view(project.id)

    return render_template(
        'public/projectboost.html',
        current_event=event, project=project, form=form,
        active="dribs"
    )


@blueprint.route('/<int:project_id>/render', methods=['GET'])
def render(project_id):
    """Transform project detail link."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    return render_template(
        'render.html',
        current_event=project.event, render_src=project.webpage_url
    )


@blueprint.route('/<int:project_id>/post', methods=['GET', 'POST'])
@login_required
def project_post(project_id):
    """Add a Post to a project."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    event = project.event
    starred = IsProjectStarred(project, current_user)
    allow_post = starred
    if not allow_post:
        flash('You do not have access to post to this project.', 'warning')
        return project_action(project_id, None)

    # Evaluate project progress
    stage, all_valid = validateProjectData(project)
    form = ProjectPost(obj=project, next=request.args.get('next'))

    # Process form
    if form.validate_on_submit():
        if form.has_progress.data:
            # Check and update progress
            found_next = False
            if all_valid:
                for a in projectProgressList(True, False):
                    if found_next:
                        project.progress = a[0]
                        flash("Promoted to stage '%s'" %
                              project.progress, 'info')
                        break
                    if a[0] == project.progress or \
                        not project.progress or \
                            project.progress < 0:
                        found_next = True
            # if not all_valid or not found_next:
            #    flash('Your project did not meet stage requirements.', 'info')

        # Update project data
        del form.id
        del form.has_progress
        form.populate_obj(project)
        project.update()
        db.session.add(project)
        db.session.commit()
        cache.clear()
        project_action(project_id, 'update',
                       action='post', text=form.note.data)

        flash("Thanks for sharing!", 'success')

        # Continue with project autoupdate
        if project.is_autoupdateable:
            return project_autoupdate(project.id)
        else:
            return redirect(url_for(
                'project.project_view_posted', project_id=project.id))

    return render_template(
        'public/projectpost.html',
        current_event=event, project=project, form=form,
        stage=stage, all_valid=all_valid,
        active="dribs"
    )


@blueprint.route('/<int:project_id>/comment', methods=['GET', 'POST'])
@login_required
def project_comment(project_id):
    """Use Post as comments by non-team members."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    event = project.event
    form = ProjectComment(obj=project, next=request.args.get('next'))
    # Process form
    if form.validate_on_submit():
        # Update project data
        project_action(project_id, 'review',
                       action='post', text=form.note.data)

        flash("Thanks for your feedback!", 'success')
        return redirect(url_for(
            'project.project_view_posted', project_id=project.id))

    return render_template(
        'public/projectpost.html',
        current_event=event, project=project, form=form,
        active="dribs"
    )


@blueprint.route('/<int:project_id>/unpost/<int:activity_id>', methods=['GET'])
@login_required
def post_delete(project_id, activity_id):
    """Delete a Post."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    purl = url_for('project.project_view_posted', project_id=project.id)
    activity = Activity.query.filter_by(id=activity_id).first_or_404()
    if not activity.may_delete(current_user):
        flash('No permission to delete.', 'warning')
    else:
        activity.delete()
        flash('The post has been deleted.', 'success')
    return redirect(purl)


@blueprint.route('/<int:project_id>/undo/<int:activity_id>', methods=['GET'])
@login_required
def post_revert(project_id, activity_id):
    """Revert project to a previous version."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    purl = url_for('project.project_view_posted', project_id=project.id)
    starred = IsProjectStarred(project, current_user)
    if not isUserActive(current_user) or not starred:
        flash('Could not revert: user not allowed.', 'warning')
        return redirect(purl)
    activity = Activity.query.filter_by(id=activity_id).first_or_404()
    if not activity.project_version:
        flash('Could not revert: data not available.', 'warning')
    elif activity.project_version == 0:
        flash('Could not revert: this is the earliest version.', 'warning')
    else:
        revert_to = activity.project_version
        project.versions[revert_to - 1].revert()
        flash('Project data reverted to version %d.' % revert_to, 'success')
        return project_view(project.id)
    return redirect(purl)


@blueprint.route('/<int:project_id>/star/me', methods=['GET', 'POST'])
@login_required
def project_star(project_id):
    """Join a project."""
    if not isUserActive(current_user):
        flash(
            "User currently not allowed to join projects - please contact "
            + " organizers for activation.", 'warning'
        )
        return redirect(url_for('project.project_view', project_id=project_id))
    flash('Welcome to the team!', 'success')
    return project_action(project_id, 'star', then_redirect=True)


@blueprint.route('/<int:project_id>/star', methods=['POST'])
@login_required
@admin_required
def project_star_user(project_id):
    """Join a project by username (via form)."""
    username = request.form['username'].strip()
    user = User.query.filter(User.username.ilike(username)).first()
    if user is None:
        flash("User [%s] not found. Please try again." % username, 'warning')
        return redirect(url_for('project.project_view', project_id=project_id))
    flash('Added %s to the team!' % username, 'success')
    return project_action(
        project_id, 'star', then_redirect=True, for_user=user)


@blueprint.route('/<int:project_id>/unstar/me', methods=['GET', 'POST'])
@login_required
def project_unstar_me(project_id):
    """Leave a project."""
    flash('You have left the project', 'success')
    return project_action(project_id, 'unstar', then_redirect=True)


@blueprint.route('/<int:project_id>/unstar/<int:user_id>', methods=['GET'])
@login_required
@admin_required
def project_unstar(project_id, user_id):
    """Kick a user from a project."""
    user = User.query.filter_by(id=user_id).first_or_404()
    project = Project.query.filter_by(id=project_id).first_or_404()
    flash('User %s has left the project' % user.username, 'success')
    return project_action(
        project.id, 'unstar', then_redirect=True, for_user=user
    )


@blueprint.route('/event/<int:event_id>/project/new', methods=['GET', 'POST'])
@login_required
def project_new(event_id):
    """If allowed to create a new project, do so."""
    if not isUserActive(current_user):
        flash(
            "Your account needs to be activated - "
            + " please contact an organizer.", 'warning'
        )
        return redirect(url_for('public.event', event_id=event_id))
    event = Event.query.filter_by(id=event_id).first_or_404()
    if event.lock_starting:
        flash('Starting a new project is disabled for this event.', 'error')
        return redirect(url_for('public.event', event_id=event.id))
    if not isUserActive(current_user):
        flash('Your user account is not permitted to start projects.', 'error')
        return redirect(url_for('public.event', event_id=event.id))
    # Checks passed, continue ...
    return create_new_project(event)


def create_new_project(event):
    """Proceed to create a new project."""
    # Collect resource tips (stage 0 projects)
    suggestions = resources_by_stage(0, event.lock_resources)

    # Project form
    form = None
    project = Project()
    project.user_id = current_user.id
    form = ProjectNew(obj=project, next=request.args.get('next'))
    form.category_id.choices = [(c.id, c.name)
                                for c in project.categories_all(event)]
    if len(form.category_id.choices) > 0:
        form.category_id.choices.insert(0, (-1, ''))
    else:
        del form.category_id

    if not form.validate_on_submit():
        return render_template(
            'public/projectnew.html',
            current_event=event, form=form, suggestions=suggestions,
            active="projects"
        )

    # Process form result
    tpl_id = None
    if form.template.data:
        tpl_id = form.template.data
    del form.id
    del form.template
    form.populate_obj(project)

    # Apply template, if selected
    if tpl_id:
        template = Project.query.get(tpl_id)
        project.longtext = template.longtext
        project.image_url = template.image_url
        project.source_url = template.source_url
        project.webpage_url = template.webpage_url
        project.download_url = template.download_url

    # Start as challenge
    project.progress = -1
    project.event = event
    # Unless the event has started
    if event.has_started:
        project.progress = 5

    # Update the project
    project.update()
    db.session.add(project)
    db.session.commit()
    cache.clear()

    flash('Now invite your team to Join this page!', 'success')
    project_action(project.id, 'create', False)

    # Automatically join new projects
    if event.has_started:
        project_action(project.id, 'star', False)

    # Automatically sync data
    if len(project.autotext_url) > 1:
        return project_autoupdate(project.id)

    # Continue to project view
    purl = url_for('project.project_view', project_id=project.id)
    return redirect(purl)


@blueprint.route('/<int:project_id>/autoupdate')
@login_required
def project_autoupdate(project_id):
    """Sync remote project data."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    if not project.is_autoupdateable:
        return project_action(project_id)

    # Check user permissions
    starred = IsProjectStarred(project, current_user)
    allow_edit = starred or (
        not current_user.is_anonymous and current_user.is_admin)
    if not allow_edit or project.is_hidden:
        flash('You may not sync this project.', 'warning')
        return redirect(url_for('project.project_view', project_id=project_id))

    # Start update process
    has_autotext = project.autotext and len(project.autotext) > 1
    data = GetProjectData(project.autotext_url)
    if not data or 'name' not in data:
        flash("To Sync: ensure a README on the remote site.", 'warning')
        return redirect(url_for('project.project_view', project_id=project_id))
    SyncProjectData(project, data)

    # Confirmation messages
    if not has_autotext:
        if project.autotext and len(project.autotext) > 1:
            project_action(project.id, 'update', action='sync',
                           text=str(len(project.autotext)) + ' bytes')
            flash("Thanks for contributing on %s" % data['type'], 'success')
        else:
            flash("Could not sync: remote README has no data.", 'warning')
    return redirect(url_for(
        'project.project_view_posted', project_id=project_id))


@blueprint.route('/project/<int:project_id>/toggle', methods=['GET', 'POST'])
@login_required
def project_toggle(project_id):
    """Hide or unhide a project."""
    project = Project.query.filter_by(id=project_id).first_or_404()
    purl = url_for('project.project_view', project_id=project.id)
    allow_toggle = IsProjectStarred(project, current_user) \
        or (not current_user.is_anonymous and current_user.is_admin)
    if not allow_toggle:
        flash("You do not have permission to change visibility.", 'warning')
        return redirect(purl)
    project.is_hidden = not project.is_hidden
    project.save()
    cache.clear()
    if project.is_hidden:
        flash('Project "%s" is now hidden.' % project.name, 'success')
    else:
        flash('Project "%s" is now visible.' % project.name, 'success')
    return redirect(purl)
