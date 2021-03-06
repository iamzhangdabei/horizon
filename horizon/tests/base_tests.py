# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2012 Openstack, LLC
# Copyright 2012 Nebula, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from django.conf import settings
from django.core import urlresolvers
from django.test.client import Client
from django.utils.importlib import import_module
from django.utils.translation import ugettext_lazy as _

import horizon
from horizon import base
from horizon import test
from horizon import users
from horizon.dashboards.nova.dashboard import Nova
from horizon.dashboards.syspanel.dashboard import Syspanel
from horizon.dashboards.settings.dashboard import Settings
from horizon.tests.test_dashboards.cats.dashboard import Cats
from horizon.tests.test_dashboards.cats.kittens.panel import Kittens
from horizon.tests.test_dashboards.cats.tigers.panel import Tigers
from horizon.tests.test_dashboards.dogs.dashboard import Dogs
from horizon.tests.test_dashboards.dogs.puppies.panel import Puppies


class MyDash(horizon.Dashboard):
    name = _("My Dashboard")
    slug = "mydash"
    default_panel = "myslug"


class MyPanel(horizon.Panel):
    name = _("My Panel")
    slug = "myslug"
    services = ("compute",)
    urls = 'horizon.tests.test_panel_urls'


class AdminPanel(horizon.Panel):
    name = _("Admin Panel")
    slug = "admin_panel"
    roles = ("admin",)
    urls = 'horizon.tests.test_panel_urls'


class BaseHorizonTests(test.TestCase):
    def setUp(self):
        super(BaseHorizonTests, self).setUp()
        # Adjust our horizon config and register our custom dashboards/panels.
        self.old_default_dash = settings.HORIZON_CONFIG['default_dashboard']
        settings.HORIZON_CONFIG['default_dashboard'] = 'cats'
        self.old_dashboards = settings.HORIZON_CONFIG['dashboards']
        settings.HORIZON_CONFIG['dashboards'] = ('cats', 'dogs')
        base.Horizon.register(Cats)
        base.Horizon.register(Dogs)
        Cats.register(Kittens)
        Cats.register(Tigers)
        Dogs.register(Puppies)
        # Trigger discovery, registration, and URLconf generation if it
        # hasn't happened yet.
        base.Horizon._urls()
        # Store our original dashboards
        self._discovered_dashboards = base.Horizon._registry.keys()
        # Gather up and store our original panels for each dashboard
        self._discovered_panels = {}
        for dash in self._discovered_dashboards:
            panels = base.Horizon._registry[dash]._registry.keys()
            self._discovered_panels[dash] = panels
        # Remove the OpenStack dashboards for test isolation.
        base.Horizon.unregister(Nova)
        base.Horizon.unregister(Syspanel)
        base.Horizon.unregister(Settings)

    def tearDown(self):
        super(BaseHorizonTests, self).tearDown()
        # Restore our settings
        settings.HORIZON_CONFIG['default_dashboard'] = self.old_default_dash
        settings.HORIZON_CONFIG['dashboards'] = self.old_dashboards
        # Destroy our singleton and re-create it.
        base.HorizonSite._instance = None
        del base.Horizon
        base.Horizon = base.HorizonSite()
        # Re-register the OpenStack dashboards that we removed.
        base.Horizon.register(Nova)
        base.Horizon.register(Syspanel)
        base.Horizon.register(Settings)
        # Reload the convenience references to Horizon stored in __init__
        reload(import_module("horizon"))
        # Re-register our original dashboards and panels.
        # This is necessary because autodiscovery only works on the first
        # import, and calling reload introduces innumerable additional
        # problems. Manual re-registration is the only good way for testing.
        self._discovered_dashboards.remove(Cats)
        self._discovered_dashboards.remove(Dogs)
        for dash in self._discovered_dashboards:
            base.Horizon.register(dash)
            for panel in self._discovered_panels[dash]:
                dash.register(panel)

    def _reload_urls(self):
        '''
        Clears out the URL caches, reloads the root urls module, and
        re-triggers the autodiscovery mechanism for Horizon. Allows URLs
        to be re-calculated after registering new dashboards. Useful
        only for testing and should never be used on a live site.
        '''
        urlresolvers.clear_url_caches()
        reload(import_module(settings.ROOT_URLCONF))
        base.Horizon._urls()


class HorizonTests(BaseHorizonTests):
    def test_registry(self):
        """ Verify registration and autodiscovery work correctly.

        Please note that this implicitly tests that autodiscovery works
        by virtue of the fact that the dashboards listed in
        ``settings.INSTALLED_APPS`` are loaded from the start.
        """
        # Registration
        self.assertEqual(len(base.Horizon._registry), 2)
        horizon.register(MyDash)
        self.assertEqual(len(base.Horizon._registry), 3)
        with self.assertRaises(ValueError):
            horizon.register(MyPanel)
        with self.assertRaises(ValueError):
            horizon.register("MyPanel")

        # Retrieval
        my_dash_instance_by_name = horizon.get_dashboard("mydash")
        self.assertTrue(isinstance(my_dash_instance_by_name, MyDash))
        my_dash_instance_by_class = horizon.get_dashboard(MyDash)
        self.assertEqual(my_dash_instance_by_name, my_dash_instance_by_class)
        with self.assertRaises(base.NotRegistered):
            horizon.get_dashboard("fake")
        self.assertQuerysetEqual(horizon.get_dashboards(),
                                 ['<Dashboard: cats>',
                                  '<Dashboard: dogs>',
                                  '<Dashboard: mydash>'])

        # Removal
        self.assertEqual(len(base.Horizon._registry), 3)
        horizon.unregister(MyDash)
        self.assertEqual(len(base.Horizon._registry), 2)
        with self.assertRaises(base.NotRegistered):
            horizon.get_dashboard(MyDash)

    def test_site(self):
        self.assertEqual(unicode(base.Horizon), "Horizon")
        self.assertEqual(repr(base.Horizon), "<Site: horizon>")
        dash = base.Horizon.get_dashboard('cats')
        self.assertEqual(base.Horizon.get_default_dashboard(), dash)
        user = users.User()
        self.assertEqual(base.Horizon.get_user_home(user),
                         dash.get_absolute_url())

    def test_dashboard(self):
        cats = horizon.get_dashboard("cats")
        self.assertEqual(cats._registered_with, base.Horizon)
        self.assertQuerysetEqual(cats.get_panels(),
                                 ['<Panel: kittens>',
                                  '<Panel: tigers>'])
        self.assertEqual(cats.get_absolute_url(), "/cats/")

        # Test registering a module with a dashboard that defines panels
        # as a panel group.
        cats.register(MyPanel)
        self.assertQuerysetEqual(cats.get_panel_groups()['other'],
                                 ['<Panel: myslug>'])

        # Test that panels defined as a tuple still return a PanelGroup
        dogs = horizon.get_dashboard("dogs")
        self.assertQuerysetEqual(dogs.get_panel_groups().values(),
                                 ['<PanelGroup: default>'])

        # Test registering a module with a dashboard that defines panels
        # as a tuple.
        dogs = horizon.get_dashboard("dogs")
        dogs.register(MyPanel)
        self.assertQuerysetEqual(dogs.get_panels(),
                                 ['<Panel: puppies>',
                                  '<Panel: myslug>'])

    def test_panels(self):
        cats = horizon.get_dashboard("cats")
        tigers = cats.get_panel("tigers")
        self.assertEqual(tigers._registered_with, cats)
        self.assertEqual(tigers.get_absolute_url(), "/cats/tigers/")

    def test_index_url_name(self):
        cats = horizon.get_dashboard("cats")
        tigers = cats.get_panel("tigers")
        tigers.index_url_name = "does_not_exist"
        with self.assertRaises(urlresolvers.NoReverseMatch):
            tigers.get_absolute_url()
        tigers.index_url_name = "index"
        self.assertEqual(tigers.get_absolute_url(), "/cats/tigers/")

    def test_lazy_urls(self):
        urlpatterns = horizon.urls[0]
        self.assertTrue(isinstance(urlpatterns, base.LazyURLPattern))
        # The following two methods simply should not raise any exceptions
        iter(urlpatterns)
        reversed(urlpatterns)

    def test_horizon_test_isolation_1(self):
        """ Isolation Test Part 1: sets a value. """
        cats = horizon.get_dashboard("cats")
        cats.evil = True

    def test_horizon_test_isolation_2(self):
        """ Isolation Test Part 2: The value set in part 1 should be gone. """
        cats = horizon.get_dashboard("cats")
        self.assertFalse(hasattr(cats, "evil"))

    def test_public(self):
        users.get_user_from_request = self._real_get_user_from_request
        dogs = horizon.get_dashboard("dogs")
        # Known to have no restrictions on it other than being logged in.
        puppies = dogs.get_panel("puppies")
        url = puppies.get_absolute_url()
        # Get a clean, logged out client instance.
        client = Client()
        client.logout()
        resp = client.get(url)
        redirect_url = "?".join([urlresolvers.reverse("horizon:auth_login"),
                                 "next=%s" % url])
        self.assertRedirectsNoFollow(resp, redirect_url)
        # Simulate ajax call
        resp = client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        # Response should be HTTP 401 with redirect header
        self.assertEquals(resp.status_code, 401)
        self.assertEquals(resp["X-Horizon-Location"],
                          "?".join([urlresolvers.reverse("horizon:auth_login"),
                                    "next=%s" % url]))

    def test_required_services(self):
        horizon.register(MyDash)
        MyDash.register(MyPanel)
        dash = horizon.get_dashboard("mydash")
        panel = dash.get_panel('myslug')
        self._reload_urls()

        # With the required service, the page returns fine.
        resp = self.client.get(panel.get_absolute_url())
        self.assertEqual(resp.status_code, 200)

        # Remove the required service from the service catalog and we
        # should get a 404.
        new_catalog = [service for service in self.request.user.service_catalog
                       if service['type'] != MyPanel.services[0]]
        tenants = self.context['authorized_tenants']
        self.setActiveUser(token=self.token.id,
                           username=self.user.name,
                           tenant_id=self.tenant.id,
                           service_catalog=new_catalog,
                           authorized_tenants=tenants)
        resp = self.client.get(panel.get_absolute_url())
        self.assertEqual(resp.status_code, 404)

    def test_required_roles(self):
        dash = horizon.get_dashboard("cats")
        panel = dash.get_panel('tigers')

        # Non-admin user
        self.setActiveUser(token=self.token.id,
                           username=self.user.name,
                           tenant_id=self.tenant.id,
                           service_catalog=self.service_catalog,
                           roles=[])

        resp = self.client.get(panel.get_absolute_url())
        self.assertEqual(resp.status_code, 302)

        resp = self.client.get(panel.get_absolute_url(),
                               follow=False,
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 401)

        # Set roles for admin user
        self.setActiveUser(token=self.token.id,
                           username=self.user.name,
                           tenant_id=self.tenant.id,
                           service_catalog=self.request.user.service_catalog,
                           roles=[{'name': 'admin'}])

        resp = self.client.get(panel.get_absolute_url())
        self.assertEqual(resp.status_code, 200)

        # Test modal form
        resp = self.client.get(panel.get_absolute_url(),
                               follow=False,
                               HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp.status_code, 200)
