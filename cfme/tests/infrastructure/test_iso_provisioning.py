import fauxfactory
import pytest
from widgetastic.utils import partial_match

from cfme import test_requirements
from cfme.infrastructure.provider import InfraProvider
from cfme.infrastructure.pxe import get_template_from_config
from cfme.infrastructure.pxe import ISODatastore
from cfme.provisioning import do_vm_provisioning
from cfme.utils import testgen
from cfme.utils.conf import cfme_data

pytestmark = [
    pytest.mark.meta(server_roles="+automate"),
    pytest.mark.usefixtures('uses_infra_providers'),
    pytest.mark.tier(2)
]


def pytest_generate_tests(metafunc):
    # Filter out providers without provisioning data or hosts defined
    argnames, argvalues, idlist = testgen.providers_by_class(
        metafunc, [InfraProvider], required_fields=[
            ('iso_datastore', True),
            ['provisioning', 'host'],
            ['provisioning', 'datastore'],
            ['provisioning', 'iso_template'],
            ['provisioning', 'iso_file'],
            ['provisioning', 'iso_kickstart'],
            ['provisioning', 'iso_root_password'],
            ['provisioning', 'iso_image_type'],
            ['provisioning', 'vlan'],
        ])

    new_idlist = []
    new_argvalues = []
    for i, argvalue_tuple in enumerate(argvalues):
        args = dict(list(zip(argnames, argvalue_tuple)))
        if args['provider'].type == "scvmm":
            continue

        iso_cust_template = args['provider'].data['provisioning']['iso_kickstart']
        if iso_cust_template not in list(cfme_data.get('customization_templates', {}).keys()):
            continue

        new_idlist.append(idlist[i])
        new_argvalues.append(argvalues[i])

    testgen.parametrize(metafunc, argnames, new_argvalues, ids=new_idlist, scope="module")


@pytest.fixture(scope="module")
def iso_cust_template(provider, appliance):
    iso_cust_template = provider.data['provisioning']['iso_kickstart']
    return get_template_from_config(iso_cust_template, create=True, appliance=appliance)


@pytest.fixture(scope="module")
def iso_datastore(provider, appliance):
    return ISODatastore(provider.name, appliance=appliance)


@pytest.fixture
def datastore_init(iso_cust_template, iso_datastore, provisioning, setup_provider, appliance):
    if not iso_datastore.exists():
        iso_datastore.create()
    iso_image_type = appliance.collections.system_image_types.instantiate(
        name=provisioning['iso_image_type'])
    iso_image = appliance.collections.system_images.instantiate(
        name=provisioning['iso_file'], image_type=iso_image_type, datastore=iso_datastore)
    iso_image.set_image_type()


@pytest.fixture(scope="function")
def vm_name():
    vm_name = fauxfactory.gen_alphanumeric(20, start="test_iso_prov_")
    return vm_name


@pytest.mark.tier(2)
@test_requirements.provision
def test_iso_provision_from_template(appliance, provider, vm_name, datastore_init, request):
    """Tests ISO provisioning

    Metadata:
        test_flag: iso, provision
        suite: infra_provisioning

    Polarion:
        assignee: jhenner
        caseimportance: high
        casecomponent: Provisioning
        initialEstimate: 1/4h
    """
    # generate_tests makes sure these have values
    (iso_template,
     host,
     datastore,
     iso_file,
     iso_kickstart,
     iso_root_password,
     iso_image_type,
     vlan,
     addr_mode) = tuple(map(provider.data['provisioning'].get,
                            ('pxe_template',
                             'host',
                             'datastore',
                             'iso_file',
                             'iso_kickstart',
                             'iso_root_password',
                             'iso_image_type',
                             'vlan',
                             'iso_address_mode')))

    request.addfinalizer(lambda:
                         appliance.collections.infra_vms.instantiate(vm_name, provider)
                         .cleanup_on_provider())

    provisioning_data = {
        'catalog': {
            'vm_name': vm_name,
            'provision_type': 'ISO',
            'iso_file': {'name': iso_file}},
        'environment': {
            'host_name': {'name': host},
            'datastore_name': {'name': datastore}},
        'customize': {
            'custom_template': {'name': iso_kickstart},
            'root_password': iso_root_password,
            'address_mode': addr_mode},
        'network': {
            'vlan': partial_match(vlan)},
        'schedule': {
            'power_on': False}}
    do_vm_provisioning(appliance, iso_template, provider, vm_name, provisioning_data, request,
                       num_sec=1800)
