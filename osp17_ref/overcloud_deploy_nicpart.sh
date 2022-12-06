#!/bin/bash

PARAMS="$*"
USER_THT="$HOME/osp17_ref"

if [ ! -d /home/stack/images ]; then
    mkdir -p /home/stack/images
    pushd /home/stack/images
    for i in /usr/share/rhosp-director-images/overcloud-hardened-uefi-full.tar /usr/share/rhosp-director-images/ironic-python-agent-latest.tar; do tar -xvf $i; done
    sudo yum install libguestfs-tools -y
    export LIBGUESTFS_BACKEND=direct
    virt-sysprep --operation machine-id -a overcloud-hardened-uefi-full.tar
    openstack overcloud image upload --image-path /home/stack/images/ --update-existing
    for i in $(openstack baremetal node list -c UUID -f value); do openstack overcloud node configure --boot-mode "uefi" $i; done
    popd
fi

# Always generate roles_data file
openstack overcloud roles generate -o $HOME/roles_data.yaml Controller ComputeSriov ComputeOvsDpdkSriov

openstack overcloud deploy $PARAMS \
    --templates \
    --timeout 120 --ntp-server clock1.rdu2.redhat.com \
    --stack overcloud \
    -r /home/stack/roles_data.yaml \
    --deployed-server \
    --baremetal-deployment /home/stack/osp17_ref/network/baremetal_deployment.yaml \
    --vip-file /home/stack/osp17_ref/network/vip_data.yaml \
    -n /home/stack/osp17_ref/network/network_data_v2.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/network-isolation.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/network-environment.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovs.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovs-dpdk.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-sriov.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/disable-telemetry.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/debug.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/config-debug.yaml \
    -e $USER_THT/network-environment.yaml \
    -e $USER_THT/network-environment-nicpart.yaml \
    -e $USER_THT/ml2-ovs-nfv.yaml \
    -e $HOME/containers-prepare-parameter.yaml \
    --log-file overcloud_deployment.log
