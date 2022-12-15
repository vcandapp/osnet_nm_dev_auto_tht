#!/bin/bash

PARAMS="$*"
USER_THT="$HOME/osp17_ref"

# Always generate roles_data file
openstack overcloud roles generate -o $HOME/roles_data.yaml ControllerSriov ComputeOvsDpdkSriov

openstack overcloud deploy $PARAMS \
    --templates /usr/share/openstack-tripleo-heat-templates \
    --ntp-server clock.redhat.com,time1.google.com,time2.google.com,time3.google.com,time4.google.com \
    --stack overcloud \
    -r /home/stack/roles_data.yaml \
    --deployed-server \
    -e /home/stack/templates/overcloud-baremetal-deployed.yaml \
    -e /home/stack/templates/overcloud-networks-deployed.yaml \
    -e /home/stack/templates/overcloud-vip-deployed.yaml \
    -n /home/stack/osp17_ref/network/network_data_v2.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/disable-telemetry.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/debug.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/config-debug.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovs.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovs-dpdk.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-sriov.yaml \
    -e $USER_THT/network-environment.yaml \
    -e $USER_THT/network-environment-nicpart.yaml \
    -e $USER_THT/ml2-ovs-nfv.yaml \
    -e $HOME/containers-prepare-parameter.yaml \
    --disable-validations \
    --log-file overcloud_deployment.log
