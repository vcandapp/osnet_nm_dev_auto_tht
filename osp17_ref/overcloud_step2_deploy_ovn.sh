#!/bin/bash

echo "Deploying pre-provisioned overcloud nodes...."
openstack overcloud deploy $PARAMS \
    --templates /usr/share/openstack-tripleo-heat-templates \
    --timeout 120  --ntp-server clock1.rdu2.redhat.com \
    --stack overcloud \
    -r /home/stack/roles_data.yaml \
    -n /home/stack/osp17_ref/network/network_data_v2.yaml \
    --deployed-server \
    -e /home/stack/templates/overcloud-baremetal-deployed.yaml \
    -e /home/stack/templates/overcloud-networks-deployed.yaml \
    -e /home/stack/templates/vip-deployed-environment.yaml \
    -e
/usr/share/openstack-tripleo-heat-templates/environments/deployed-server-environment.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/disable-telemetry.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/debug.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/config-debug.yaml \
    -e /home/stack/osp17_ref/network-environment.yaml \
    -e /home/stack/osp17_ref/network-environment-regular.yaml \
    -e /home/stack/osp17_ref/ml2-ovs-nfv.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovn-sriov.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovn-dpdk.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovn-ha.yaml \
    -e /home/stack/containers-prepare-parameter.yaml \
    --disable-validations \
    --log-file overcloud_deployment.log
