#!/usr/bin/bash

set -ex

USER_THT="$HOME/osp17_ref"

rm -rf /home/stack/images
mkdir -p /home/stack/images
cd /home/stack/images
for i in /usr/share/rhosp-director-images/overcloud-full-latest.tar /usr/share/rhosp-director-images/ironic-python-agent-latest.tar; do tar -xvf $i; done

sudo yum install libguestfs-tools -y
sudo yum install /usr/bin/virt-sysprep -y
export LIBGUESTFS_BACKEND=direct
rm -rf /home/stack/images/os-net-config

git clone https://github.com/openstack/os-net-config.git
cd /home/stack/images/os-net-config
git fetch https://review.opendev.org/openstack/os-net-config refs/changes/52/859552/17 && git checkout FETCH_HEAD
virt-copy-in -a /home/stack/images/overcloud-full.qcow2  /home/stack/images/os-net-config/os_net_config /usr/lib/python3.9/site-packages
#If image is uefi, the use this option
#virt-customize -a overcloud-hardened-uefi-full.qcow2 --upload /home/stack/images/os-net-config/os_net_config/impl_nmstate.py:/usr/lib/python3.9/site-packages/os_net_config/impl_nmstate.py
virt-customize --selinux-relabel -a /home/stack/images/overcloud-full.qcow2
openstack overcloud image upload --image-path /home/stack/images/ --update-existing
for i in $(openstack baremetal node list -c UUID -f value); do openstack overcloud node configure --boot-mode "bios" $i; done
openstack overcloud node configure --boot-mode "bios" compute-0
popd
