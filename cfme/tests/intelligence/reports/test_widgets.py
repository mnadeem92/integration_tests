from random import choice

import fauxfactory
import pytest
from dateparser import parse

from cfme import test_requirements
from cfme.automate.simulation import simulate
from cfme.intelligence.reports.dashboards import DefaultDashboard
from cfme.intelligence.reports.widgets import AllDashboardWidgetsView
from cfme.utils.appliance.implementations.rest import ViaREST
from cfme.utils.appliance.implementations.ui import navigate_to
from cfme.utils.appliance.implementations.ui import ViaUI
from cfme.utils.blockers import BZ
from cfme.utils.rest import assert_response
from cfme.utils.update import update
from cfme.utils.wait import wait_for


@pytest.fixture(scope="module")
def default_widgets():
    view = navigate_to(DefaultDashboard(), 'Details')
    return view.selected_items


@pytest.fixture(scope="module")
def dashboard(default_widgets):
    return DefaultDashboard(widgets=default_widgets)


@pytest.fixture(scope="function")
def custom_widgets(appliance):
    collection = appliance.collections.dashboard_report_widgets
    ws = [
        collection.create(
            collection.MENU,
            fauxfactory.gen_alphanumeric(),
            description=fauxfactory.gen_alphanumeric(),
            active=True,
            shortcuts={
                "Services / Catalogs": fauxfactory.gen_alphanumeric(),
                "Compute / Clouds / Providers": fauxfactory.gen_alphanumeric(),
            },
            visibility="<To All Users>"),
        collection.create(
            collection.REPORT,
            fauxfactory.gen_alphanumeric(),
            description=fauxfactory.gen_alphanumeric(),
            active=True,
            filter=["Events", "Operations", "Operations VMs Powered On/Off for Last Week"],
            columns=["VM Name", "Message"],
            rows="10",
            timer={"run": "Hourly", "hours": "Hour"},
            visibility="<To All Users>"),
        collection.create(
            collection.CHART,
            fauxfactory.gen_alphanumeric(),
            description=fauxfactory.gen_alphanumeric(),
            active=True,
            filter="Configuration Management/Virtual Machines/Vendor and Guest OS",
            timer={"run": "Hourly", "hours": "Hour"},
            visibility="<To All Users>"),
    ]

    # RSS Removed in 5.11 (BZ 1728328)
    if appliance.version < '5.11':
        ws.append(collection.create(
            collection.RSS,
            fauxfactory.gen_alphanumeric(),
            description=fauxfactory.gen_alphanumeric(),
            active=True,
            type="Internal",
            feed="Administrative Events",
            rows="8",
            visibility="<To All Users>"))
    yield ws
    map(lambda w: w.delete(), ws)


@test_requirements.dashboard
@pytest.mark.tier(3)
def test_widgets_on_dashboard(appliance, request, dashboard, default_widgets,
                              custom_widgets, soft_assert):
    """
    Polarion:
        assignee: jhenner
        casecomponent: Reporting
        caseimportance: medium
        initialEstimate: 1/12h
    """
    with update(dashboard):
        dashboard.widgets = map(lambda w: w.title, custom_widgets)

    def _finalize():
        with update(dashboard):
            dashboard.widgets = default_widgets
    request.addfinalizer(_finalize)
    view = navigate_to(appliance.server, "Dashboard")
    view.reset_widgets()
    dashboard_view = view.dashboards("Default Dashboard")
    soft_assert(len(dashboard_view.widgets.read()) == len(custom_widgets),
                "Count of the widgets differ")
    for custom_w in custom_widgets:
        soft_assert(dashboard_view.widgets(custom_w.title).is_displayed,
                    f"Widget {custom_w.title} not found on dashboard")


@test_requirements.dashboard
@pytest.mark.tier(3)
def test_widgets_reorder_in_reports(request, dashboard):
    """Tests drag and drop widgets in Cloud Intel/Reports/Dashboards

    Polarion:
        assignee: jhenner
        casecomponent: Reporting
        caseimportance: medium
        initialEstimate: 1/6h
    """
    view = navigate_to(dashboard, "Edit")
    previous_names = view.widget_picker.all_dashboard_widgets
    first_widget = previous_names[0]
    second_widget = previous_names[1]
    view.widget_picker.drag_and_drop(first_widget, second_widget)
    new_names = view.widget_picker.all_dashboard_widgets
    assert previous_names[2:] == new_names[2:]
    assert previous_names[0] == new_names[1]
    assert previous_names[1] == new_names[0]


@test_requirements.automate
@pytest.mark.tier(1)
def test_generate_widget_content_by_automate(request, appliance, klass, namespace, domain):
    """
    Polarion:
        assignee: ghubale
        initialEstimate: 1/8h
        caseimportance: medium
        caseposneg: positive
        testtype: functional
        startsin: 5.10
        casecomponent: Automate
        tags: automate
        testSteps:
            1. create a new widget and add this widget to dashboard
            2. Create automate method with below content:
                #
                # Description: generate widget content by calling shell command
                #
                cmd =("/var/www/miq/vmdb/bin/rails r
                      'MiqWidget.find_by_title(\"widget_name\").queue_generate_content'")
                system(cmd)
                exit MIQ_OK
            3. Execute the automate method(by simulation) and check updated time of that widget
               on dashboard.
            4. Updated status changes once we trigger the generation of a widget content from
               Automate method.
            5. Or we can check widget status by executing following commands on rails console:
                >> MiqWidget.find_by_title("widget_name")
                >> service_miq_widget = MiqAeMethodService::MiqAeServiceMiqWidget.find(widget_id)
                >> service_miq_widget.queue_generate_content (this will do same what we did with
                   automate method)
        expectedResults:
            1.
            2.
            3. Updated time of that widget on dashboard should be changes to current time of update
               by automate method.
            4.
            5. Updated time of that widget on dashboard should be changes to current time of update
               by rails.

    Bugzilla:
            1445932
    """
    widget_name = fauxfactory.gen_alphanumeric()
    schema_field = fauxfactory.gen_alphanumeric()
    # Added method with given code
    method = klass.methods.create(
        name=fauxfactory.gen_alphanumeric(),
        display_name=fauxfactory.gen_alphanumeric(),
        location='inline',
        script="""cmd =('/var/www/miq/vmdb/bin/rails r \
        "MiqWidget.find_by_title(\\'{widget}\\').queue_generate_content"')\nsystem(cmd)\n
        exit MIQ_OK""".format(widget=widget_name)
    )

    # Edited schema of class to execute method using instance
    klass.schema.add_fields({'name': schema_field, 'type': 'Method', 'data_type': 'String'})

    # Added new instance
    instance = klass.instances.create(
        name=fauxfactory.gen_alphanumeric(),
        fields={schema_field: {'value': method.name}}
    )

    # Created chart widget
    widget = appliance.collections.dashboard_report_widgets.create(
        appliance.collections.dashboard_report_widgets.CHART,
        widget_name,
        description=fauxfactory.gen_alphanumeric(),
        active=True,
        filter="Configuration Management/Virtual Machines/Vendor and Guest OS",
        timer={"run": "Hourly", "hours": "Hour"},
        visibility="<To All Users>"
    )
    request.addfinalizer(widget.delete)
    # Added newly created widget to dashboard
    view = widget.create_view(AllDashboardWidgetsView)
    view.flash.assert_message(f'Widget "{widget.title}" was saved')
    view = navigate_to(appliance.server, 'Dashboard')
    view.add_widget.item_select(widget.title)

    # Browser refresh to get update status of widget otherwise it gives None
    view = navigate_to(widget, 'Details')
    old_update = view.last_run_time.read().split(' ')[4]

    # Executed automate method using simulation
    simulate(
        appliance=appliance,
        request='Call_Instance',
        attributes_values={
            'namespace': '{domain}/{namespace}'.format(domain=domain.name,
                                                       namespace=namespace.name),
            'class': klass.name,
            'instance': instance.name
        }
    )

    # Refreshing widget to get current updated time
    widget.refresh()
    current_update = view.last_run_time.read().split(' ')[4]
    assert old_update != current_update


@pytest.mark.meta(
    automates=[1761836, 1753682],
    blockers=[BZ(1761836, unblock=lambda context: context != ViaREST)],
)
@pytest.mark.tier(3)
@test_requirements.rest
@pytest.mark.parametrize("context", [ViaUI, ViaREST])
def test_widget_generate_content_via_rest(context, appliance):
    """
    Bugzilla:
       1761836
       1623607
       1753682

    Polarion:
        assignee: pvala
        caseimportance: medium
        casecomponent: Rest
        initialEstimate: 1/4h
        testSteps:
            1. Depending on the implementation -
                i. GET /api/widgtes/:id and note the `last_generated_content_on`.
                ii. Navigate to Dashboard and note the `last_generated_content_on` for the widget.
            2. POST /api/widgets/:id
                {
                    "action": "generate_content"
                }
            3. Wait until the task completes.
            4. Depending on the implementation
                i. GET /api/widgets/:id and compare the value of `last_generated_content_on`
                    with the value noted in step 1.
                ii.  Navigate to the dashboard and check if the value was updated for the widget.
        expectedResults:
            1.
            2.
            3.
            4. Both values must be different, value must be updated.
    """
    view = navigate_to(appliance.server, "Dashboard")
    view.reset_widgets()

    # Randomly select a widget from the dashboard and obtain it's REST entity with the widget_id
    ui_widget = choice(view.dashboards("Default Dashboard").widgets)
    rest_widget = appliance.rest_api.collections.widgets.get(id=ui_widget.widget_id)

    if context == ViaUI:
        last_update = ui_widget.footer.text
        rest_widget.action.generate_content()
        assert_response(appliance)

        assert wait_for(
            lambda: parse(ui_widget.footer.text.split(" | ")[0].strip("Updated "))
            > parse(last_update.split(" | ")[0].strip("Updated ")),
            fail_func=view.browser.refresh,
            timeout=10,
            delay=2,
        )

    else:
        last_update = rest_widget.last_generated_content_on

        rest_widget.rest_api_entity.generate_content()
        assert_response(appliance)

        assert wait_for(
            lambda: rest_widget.last_generated_content_on > last_update,
            fail_func=rest_widget.reload,
            timeout=30,
            message="Wait for the widget to update",
        )
