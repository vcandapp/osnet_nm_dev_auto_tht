#!/usr/bin/bash

set -ex

sudo yum install -y  libguestfs-tools-c
rm -rf /home/stack/images
mkdir -p /home/stack/images
mkdir -p /home/stack/rpms
cd /home/stack/rpms
yum download NetworkManager-ovs
yum download mstflint
yum download python3-pyroute2

wget http://download.lab.bos.redhat.com/rcm-guest/puddles/OpenStack/rhos-release/rhos-release-latest.noarch.rpm
wget https://people.redhat.com/fge/tmp/nmstate-libs-2.2.33-0.20240911.2336git51937eb6.el9.x86_64.rpm
wget https://people.redhat.com/fge/tmp/python3-libnmstate-2.2.33-0.20240911.2336git51937eb6.el9.x86_64.rpm
wget https://people.redhat.com/fge/tmp/nmstate-2.2.33-0.20240911.2336git51937eb6.el9.x86_64.rpm

cd /home/stack/images

for i in /usr/share/rhosp-director-images/overcloud-hardened-uefi-full-latest.tar /usr/share/rhosp-director-images/ironic-python-agent-latest.tar; do tar -xvf $i; done

sudo yum install libguestfs-tools -y
export LIBGUESTFS_BACKEND=direct
rm -rf /home/stack/images/os-net-config
git clone https://github.com/os-net-config/os-net-config.git
cd /home/stack/images/os-net-config
git fetch -v --all

#Update the osnet-nm patch in the overcloud-image
virt-copy-in -a /home/stack/images/overcloud-hardened-uefi-full.qcow2 /home/stack/images/os-net-config /root
virt-copy-in -a /home/stack/images/overcloud-hardened-uefi-full.qcow2 /home/stack/rpms/*.rpm /root/

virt-customize -a /home/stack/images/overcloud-hardened-uefi-full.qcow2 --run-command 'cd /root/os-net-config;PBR_VERSION=1.2.3 python setup.py install --prefix=/usr'

virt-customize -a /home/stack/images/overcloud-hardened-uefi-full.qcow2 --run-command 'yum install -y /root/nmstate-libs-2.2.33-0.20240911.2336git51937eb6.el9.x86_64.rpm /root/python3-libnmstate-2.2.33-0.20240911.2336git51937eb6.el9.x86_64.rpm /root/nmstate-2.2.33-0.20240911.2336git51937eb6.el9.x86_64.rpm'

mkdir /home/stack/images/mnt
guestmount -a /home/stack/images/overcloud-hardened-uefi-full.qcow2  -i  /home/stack/images/mnt
guestunmount /home/stack/images/mnt

source ~/stackrc
openstack overcloud image upload --image-path /home/stack/images/ --update-existing
#openstack overcloud image upload --os-image-name overcloud-full.qcow2 --image-path /home/stack/images --update-existing

for i in $(openstack baremetal node list -c UUID -f value); do openstack overcloud node configure --boot-mode "uefi" $i; done
