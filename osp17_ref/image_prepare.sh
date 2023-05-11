#!/usr/bin/bash

set -ex

rm -rf /home/stack/images
mkdir -p /home/stack/images
cd /home/stack/images
for i in /usr/share/rhosp-director-images/overcloud-full-latest.tar /usr/share/rhosp-director-images/overcloud-hardened-uefi-full-latest.tar /usr/share/rhosp-director-images/ironic-python-agent-latest.tar; do tar -xvf $i; done

sudo yum install libguestfs-tools -y
export LIBGUESTFS_BACKEND=direct
rm -rf /home/stack/images/os-net-config
git clone https://github.com/openstack/os-net-config.git
cd /home/stack/images/os-net-config
#Update the osnet-nm patch in the overcloud-image
git fetch https://review.opendev.org/openstack/os-net-config refs/changes/52/859552/26 && git checkout FETCH_HEAD
virt-copy-in -a /home/stack/images/overcloud-full.qcow2  /home/stack/images/os-net-config/os_net_config /usr/lib/python3.9/site-packages
virt-copy-in -a /home/stack/images/overcloud-hardened-uefi-full.qcow2  /home/stack/images/os-net-config/os_net_config /usr/lib/python3.9/site-packages

virt-copy-in -a /home/stack/images/overcloud-full.qcow2  /home/stack/osp17_ref/nms29 /root
virt-copy-in -a /home/stack/images/overcloud-hardened-uefi-full.qcow2 /home/stack/osp17_ref/nms29 /root

virt-customize -a /home/stack/images/overcloud-full.qcow2 --run-command 'yum install -y /root/nms29/nmstate-2.2.9-1.el9_2.x86_64.rpm /root/nms29/nmstate-libs-2.2.9-1.el9_2.x86_64.rpm /root/nms29/python3-libnmstate-2.2.9-1.el9_2.x86_64.rpm'
virt-customize -a /home/stack/images/overcloud-hardened-uefi-full.qcow2 --run-command 'yum install -y /root/nms29/nmstate-2.2.9-1.el9_2.x86_64.rpm /root/nms29/nmstate-libs-2.2.9-1.el9_2.x86_64.rpm /root/nms29/python3-libnmstate-2.2.9-1.el9_2.x86_64.rpm'

mkdir /home/stack/images/mnt
guestmount -a /home/stack/images/overcloud-full.qcow2  -i  /home/stack/images/mnt
sed -i '/\[main\]/a no-auto-default=*' /home/stack/images/mnt/etc/NetworkManager/NetworkManager.conf 
#sed -i '/\[main\]/a sslverify=false' /home/stack/images/mnt/etc/yum.conf
guestunmount /home/stack/images/mnt
guestmount -a /home/stack/images/overcloud-hardened-uefi-full.qcow2  -i  /home/stack/images/mnt
sed -i '/\[main\]/a no-auto-default=*' /home/stack/images/mnt/etc/NetworkManager/NetworkManager.conf 
#sed -i '/\[main\]/a sslverify=false' /home/stack/images/mnt/etc/yum.conf
guestunmount /home/stack/images/mnt


virt-customize -a /home/stack/images/overcloud-full.qcow2 --root-password password:12345678
virt-customize --selinux-relabel -a /home/stack/images/overcloud-full.qcow2

virt-customize -a /home/stack/images/overcloud-hardened-uefi-full.qcow2 --root-password password:12345678
virt-customize --selinux-relabel -a /home/stack/images/overcloud-hardened-uefi-full.qcow2
openstack overcloud image upload --image-path /home/stack/images/ --update-existing
openstack overcloud image upload --os-image-name overcloud-full.qcow2 --image-path /home/stack/images --update-existing
openstack overcloud node configure --boot-mode "bios" compute-0
openstack overcloud node configure --boot-mode "uefi" controller-0
openstack overcloud node configure --boot-mode "uefi" controller-1
openstack overcloud node configure --boot-mode "uefi" controller-2

