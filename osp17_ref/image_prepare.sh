#!/usr/bin/bash

rm -rf /home/stack/images
mkdir -p /home/stack/images
pushd /home/stack/images
cd /home/stack/images
for i in /usr/share/rhosp-director-images/overcloud-full-latest.tar /usr/share/rhosp-director-images/ironic-python-agent-latest.tar; do tar -xvf $i; done

sudo yum install libguestfs-tools -y
export LIBGUESTFS_BACKEND=direct
rm -rf os-net-config
git clone https://github.com/openstack/os-net-config.git
cd os-net-config
git fetch https://review.opendev.org/openstack/os-net-config refs/changes/52/859552/19 && git checkout FETCH_HEAD
virt-copy-in -a /home/stack/images/overcloud-full.qcow2  /home/stack/osp17_ref/os-net-config/os_net_config /usr/lib/python3.9/site-packages
virt-customize --selinux-relabel -a /home/stack/images/overcloud-full.qcow2
openstack overcloud image upload --image-path /home/stack/images/ --update-existing
openstack overcloud node configure --boot-mode "bios" compute-0
popd
