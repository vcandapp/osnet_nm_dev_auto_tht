#!/bin/bash

PARAMS="$*"
USER_THT="$HOME/osp17_ref"

if [ ! -d /home/stack/images ]; then
    mkdir -p /home/stack/images
    pushd /home/stack/images
    for i in /usr/share/rhosp-director-images/overcloud-full-latest.tar /usr/share/rhosp-director-images/ironic-python-agent-latest.tar; do tar -xvf $i; done
    sudo yum install libguestfs-tools -y
    export LIBGUESTFS_BACKEND=direct
    virt-customize --root-password password:redhat -a overcloud-full.qcow2
    virt-sysprep --operation machine-id -a overcloud-full.qcow2
    openstack overcloud image upload --image-path /home/stack/images/ --update-existing
    for i in $(openstack baremetal node list -c UUID -f value); do openstack overcloud node configure $i; done
    popd
fi

echo "Creating roles..."
openstack overcloud roles generate -o $HOME/roles_data.yaml ControllerSriov ComputeOvsDpdkSriov

openstack overcloud deploy $PARAMS \
    --templates /usr/share/openstack-tripleo-heat-templates \
    --timeout 120 \
    --stack overcloud \
    --network-config \
    -r /home/stack/roles_data.yaml \
    --deployed-server \
    --baremetal-deployment /home/stack/osp17_ref/network/baremetal_deployment.yaml \
    --vip-file /home/stack/osp17_ref/network/vip_data.yaml \
    -n /home/stack/osp17_ref/network/network_data_v2.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovn-dpdk.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/services/neutron-ovn-sriov.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/disable-telemetry.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/debug.yaml \
    -e /usr/share/openstack-tripleo-heat-templates/environments/config-debug.yaml \
    -e /home/stack/osp17_ref/environment.yaml \
    -e /home/stack/osp17_ref/network-environment.yaml \
    -e /home/stack/osp17_ref/network-environment-regular.yaml \
    -e /home/stack/osp17_ref/ml2-ovs-nfv.yaml \
    -e /home/stack/containers-prepare-parameter.yaml \
    --log-file overcloud_deployment.log
