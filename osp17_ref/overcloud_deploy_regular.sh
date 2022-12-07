#!/bin/bash

PARAMS="$*"
USER_THT="$HOME/osp17_ref"

#if [ ! -d /home/stack/images ]; then
#    mkdir -p /home/stack/images
#    pushd /home/stack/images
#    for i in /usr/share/rhosp-director-images/overcloud-full-latest.tar /usr/share/rhosp-director-images/ironic-python-agent-latest.tar; do tar -xvf $i; done
#    sudo yum install libguestfs-tools -y
#    export LIBGUESTFS_BACKEND=direct
#    sudo virt-customize -a overcloud-hardened-uefi-full.qcow2 --upload nmstate/impl_nmstate.py:/usr/lib/python3.9/site-packages/os_net_config/impl_nmstate.py
#    openstack overcloud image upload --image-path /home/stack/images/ --update-existing
#    for i in $(openstack baremetal node list -c UUID -f value); do openstack overcloud node configure --boot-mode "uefi" $i; done
#    popd
#fi

echo "Creating roles..."
openstack overcloud roles generate -o $HOME/roles_data.yaml ControllerSriov ComputeOvsDpdkSriov

openstack overcloud deploy $PARAMS \
    --templates /usr/share/openstack-tripleo-heat-templates \
    --timeout 120 \
    --stack overcloud \
    --network-config \
    -r /home/stack/roles_data.yaml \
    --deployed-server \
    -e /home/stack/templates/overcloud-baremetal-deployed.yaml \
    -e /home/stack/templates/overcloud-networks-deployed.yaml \
    -e /home/stack/templates/overcloud-vip-deployed.yaml \
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
    --ntp-server clock.redhat.com,time1.google.com,time2.google.com,time3.google.com,time4.google.com \
    --log-file overcloud_deployment.log
