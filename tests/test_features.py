# -*- coding: utf-8 -*-
"""Dribdat feature tests using WebTest.

See: http://webtest.readthedocs.org/
"""
from flask import url_for
from .factories import ProjectFactory, EventFactory
from dribdat.onebox import make_onebox
from dribdat.public.projhelper import resources_by_stage, project_action


class TestProjects:
    """Project features."""

    def test_onebox(self, project, testapp):
        """Generate one box."""
        srv = url_for('public.home', _external=True)
        url = "%sproject/%d" % (srv, project.id)
        test_markdown = """Some project content
<p><a href="%s">%s</a></p>
EOF""" % (url, url)

        result = make_onebox(test_markdown)
        assert 'onebox' in result

    def test_project_api(self, project, testapp):
        """Make sure Project APIs respond correctly."""
        project = ProjectFactory()
        project.name = 'example'
        project.longtext = 'Word.'
        project.autotext = 'some test readme content'
        project.save()
        # print(project.data)
        assert 'example' in project.data['name']
        assert project.data['excerpt'] == ''
        project.autotext_url = 'https:/...'
        assert 'test' in project.autotext
        assert 'test' in project.data['excerpt']
        # test stats
        stats = project.get_stats()
        assert stats['total'] == 0
        assert stats['updates'] == 0
        assert stats['commits'] == 0
        assert stats['during'] == 0
        assert stats['people'] == 0
        assert stats['sizepitch'] == 5
        assert stats['sizetotal'] == 48
        
    def test_project_stage(self, project, testapp):
        """Check stage progression."""
        event = EventFactory()
        event.lock_resources = True
        event.hidden = False
        event.save()
        project = ProjectFactory()
        project.name = 'example resource'
        project.save()
        assert resources_by_stage(0) == []
        project.event_id = event.id
        project.progress = 0
        project.is_hidden = False
        assert project.is_challenge
        project.save()
        assert len(resources_by_stage(0)) == 1
        assert project_action(project.id)
