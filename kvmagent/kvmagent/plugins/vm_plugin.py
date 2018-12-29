'''
@author: Frank
'''
import Queue
import os.path
import tempfile
import threading
import time
import traceback
import xml.etree.ElementTree as etree
import re
import platform
import netaddr

import libvirt
#from typing import List, Any, Union

import zstacklib.utils.ip as ip
import zstacklib.utils.iptables as iptables
import zstacklib.utils.lock as lock
from kvmagent import kvmagent
from kvmagent.plugins.imagestore import ImageStoreClient
from zstacklib.utils import bash
from zstacklib.utils.bash import in_bash
from zstacklib.utils import http
from zstacklib.utils import jsonobject
from zstacklib.utils import lichbd
import zstacklib.utils.lichbd_factory as lichbdfactory
from zstacklib.utils import linux
from zstacklib.utils import log
from zstacklib.utils import lvm
from zstacklib.utils import shell
from zstacklib.utils import thread
from zstacklib.utils import uuidhelper
from zstacklib.utils import xmlobject
from zstacklib.utils import misc

logger = log.get_logger(__name__)

IS_AARCH64 = platform.machine() == 'aarch64'

ZS_XML_NAMESPACE = 'http://zstack.org'

etree.register_namespace('zs', ZS_XML_NAMESPACE)

QMP_SOCKET_PATH = "/var/lib/libvirt/qemu/zstack"

class RetryException(Exception):
    pass


class NicTO(object):
    def __init__(self):
        self.mac = None
        self.bridgeName = None
        self.deviceId = None


class StartVmCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(StartVmCmd, self).__init__()
        self.vmInstanceUuid = None
        self.vmName = None
        self.memory = None
        self.cpuNum = None
        self.cpuSpeed = None
        self.bootDev = None
        self.rootVolume = None
        self.dataVolumes = []
        self.isoPath = None
        self.nics = []
        self.timeout = None
        self.dataIsoPaths = None
        self.addons = None
        self.useBootMenu = True
        self.vmCpuModel = None
        self.emulateHyperV = False
        self.additionalQmp = True
        self.isApplianceVm = False
        self.systemSerialNumber = None
        self.bootMode = None

class StartVmResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(StartVmResponse, self).__init__()


class GetVncPortCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(GetVncPortCmd, self).__init__()
        self.vmUuid = None


class GetVncPortResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(GetVncPortResponse, self).__init__()
        self.port = None
        self.protocol = None


class ChangeCpuMemResponse(kvmagent.AgentResponse):
    def _init_(self):
        super(ChangeCpuMemResponse, self)._init_()
        self.cpuNum = None
        self.memorySize = None
        self.vmuuid

class IncreaseCpuResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(IncreaseCpuResponse, self).__init__()
        self.cpuNum = None
        self.vmUuid = None

class IncreaseMemoryResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(IncreaseMemoryResponse, self).__init__()
        self.memorySize = None
        self.vmUuid = None

class StopVmCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(StopVmCmd, self).__init__()
        self.uuid = None
        self.timeout = None


class StopVmResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(StopVmResponse, self).__init__()


class PauseVmCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(PauseVmCmd, self).__init__()
        self.uuid = None
        self.timeout = None


class PauseVmResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(PauseVmResponse, self).__init__()


class ResumeVmCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(ResumeVmCmd, self).__init__()
        self.uuid = None
        self.timeout = None


class ResumeVmResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(ResumeVmResponse, self).__init__()


class RebootVmCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(RebootVmCmd, self).__init__()
        self.uuid = None
        self.timeout = None


class RebootVmResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(RebootVmResponse, self).__init__()


class DestroyVmCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(DestroyVmCmd, self).__init__()
        self.uuid = None


class DestroyVmResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(DestroyVmResponse, self).__init__()


class VmSyncCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(VmSyncCmd, self).__init__()


class VmSyncResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(VmSyncResponse, self).__init__()
        self.states = None


class AttachDataVolumeCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(AttachDataVolumeCmd, self).__init__()
        self.volume = None
        self.uuid = None


class AttachDataVolumeResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(AttachDataVolumeResponse, self).__init__()


class DetachDataVolumeCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(DetachDataVolumeCmd, self).__init__()
        self.volume = None
        self.uuid = None


class DetachDataVolumeResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(DetachDataVolumeResponse, self).__init__()


class MigrateVmResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(MigrateVmResponse, self).__init__()


class TakeSnapshotResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(TakeSnapshotResponse, self).__init__()
        self.newVolumeInstallPath = None
        self.snapshotInstallPath = None
        self.size = None

class TakeVolumeBackupResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(TakeVolumeBackupResponse, self).__init__()
        self.backupFile = None
        self.parentInstallPath = None
        self.bitmap = None

class VolumeBackupInfo(object):
    def __init__(self, deviceId, bitmap, backupFile, parentInstallPath):
        self.deviceId = deviceId
        self.bitmap = bitmap
        self.backupFile = backupFile
        self.parentInstallPath = parentInstallPath


class TakeVolumesBackupsResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(TakeVolumesBackupsResponse, self).__init__()
        self.backupInfos = [] # type: list[VolumeBackupInfo]


class TakeSnapshotsCmd(kvmagent.AgentCommand):
    snapshotJobs = None  # type: list[VolumeSnapshotJobStruct]

    def __init__(self):
        super(TakeSnapshotsCmd, self).__init__()
        self.snapshotJobs = []


class TakeSnapshotsResponse(kvmagent.AgentResponse):
    snapshots = None  # type: List[VolumeSnapshotResultStruct]

    def __init__(self):
        super(TakeSnapshotsResponse, self).__init__()
        self.snapshots = []


class CancelBackupJobsCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(CancelBackupJobsCmd, self).__init__()
        self.vmUuid = None


class CancelBackupJobsResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(CancelBackupJobsResponse, self).__init__()


class MergeSnapshotRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(MergeSnapshotRsp, self).__init__()


class LogoutIscsiTargetRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(LogoutIscsiTargetRsp, self).__init__()


class LoginIscsiTargetRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(LoginIscsiTargetRsp, self).__init__()


class ReportVmStateCmd(object):
    def __init__(self):
        self.hostUuid = None
        self.vmUuid = None
        self.vmState = None


class CheckVmStateRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(CheckVmStateRsp, self).__init__()
        self.states = {}


class ChangeVmPasswordRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(ChangeVmPasswordRsp, self).__init__()
        self.accountPerference = None


class AccountPerference(object):
    def __init__(self):
        self.userAccount = None
        self.accountPassword = None
        self.vmUuid = None


class ReconnectMeCmd(object):
    def __init__(self):
        self.hostUuid = None
        self.reason = None

class GetPciDevicesCmd(kvmagent.AgentCommand):
    def __init__(self):
        super(GetPciDevicesCmd, self).__init__()
        self.filterString = None
        self.enableIommu = True

class GetPciDevicesResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(GetPciDevicesResponse, self).__init__()
        self.pciDevicesInfo = None
        self.hostIommuStatus = False

class HotPlugPciDeviceCommand(kvmagent.AgentCommand):
    def __init__(self):
        super(HotPlugPciDeviceCommand, self).__init__()
        self.pciDeviceAddress = None
        self.vmUuid = None

class HotPlugPciDeviceRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(HotPlugPciDeviceRsp, self).__init__()

class HotUnplugPciDeviceCommand(kvmagent.AgentCommand):
    def __init__(self):
        super(HotUnplugPciDeviceCommand, self).__init__()
        self.pciDeviceAddress = None
        self.vmUuid = None

class HotUnplugPciDeviceRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(HotUnplugPciDeviceRsp, self).__init__()

class KvmAttachUsbDeviceRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(KvmAttachUsbDeviceRsp, self).__init__()

class KvmDetachUsbDeviceRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(KvmDetachUsbDeviceRsp, self).__init__()

class CheckMountDomainRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(CheckMountDomainRsp, self).__init__()
        self.active = False
class KvmResizeVolumeCommand(kvmagent.AgentCommand):
    def __init__(self):
        super(KvmResizeVolumeCommand, self).__init__()
        self.vmUuid = None
        self.size = None
        self.deviceId = None

class KvmResizeVolumeRsp(kvmagent.AgentResponse):
    def __init__(self):
        super(KvmResizeVolumeRsp, self).__init__()

class BlockStreamResponse(kvmagent.AgentResponse):
    def __init__(self):
        super(BlockStreamResponse, self).__init__()

class VncPortIptableRule(object):
    def __init__(self):
        self.host_ip = None
        self.port = None
        self.vm_internal_id = None

    def _make_chain_name(self):
        return "vm-%s-vnc" % self.vm_internal_id

    @lock.file_lock('/run/xtables.lock')
    def apply(self):
        assert self.host_ip is not None
        assert self.port is not None
        assert self.vm_internal_id is not None

        ipt = iptables.from_iptables_save()
        chain_name = self._make_chain_name()

        # get ipv4 address via ping
        current_ip = shell.call('ping %s -c 1 | fgrep "icmp" | grep -o \'[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\'' % self.host_ip)
        if "" == current_ip:
            err = 'cannot get host ip for %s' % self.host_ip
            logger.warn(err)
            raise kvmagent.KvmError(err)

        # get ipv4 subnet
        current_ip_with_netmask = shell.call('ip -o -f inet addr show | awk \'/scope global/ {print $4}\' | fgrep %s' % current_ip).strip().split('\n', 1)[0]
        if "" == shell.call("echo %s | grep -o \'[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}\.[0-9]\{1,3\}/[0-9]\{1,2\}\'" % current_ip_with_netmask):
            err = 'cannot get host ip with netmask for %s' % self.host_ip
            logger.warn(err)
            raise kvmagent.KvmError(err)

        ipt.add_rule('-A INPUT -p tcp -m tcp --dport %s -j %s' % (self.port, chain_name))
        ipt.add_rule('-A %s -d %s -j ACCEPT' % (chain_name, current_ip_with_netmask))
        ipt.add_rule('-A %s ! -d %s -j REJECT --reject-with icmp-host-prohibited' % (chain_name, current_ip_with_netmask))
        ipt.iptable_restore()

    @lock.file_lock('/run/xtables.lock')
    def delete(self):
        assert self.vm_internal_id is not None

        ipt = iptables.from_iptables_save()
        chain_name = self._make_chain_name()
        ipt.delete_chain(chain_name)
        ipt.iptable_restore()

    @lock.file_lock('/run/xtables.lock')
    def delete_stale_chains(self):
        vms = get_running_vms()
        ipt = iptables.from_iptables_save()
        tbl = ipt.get_table()

        internal_ids = []
        for vm in vms:
            if is_namespace_used():
                vm_id_node = find_zstack_metadata_node(etree.fromstring(vm.domain_xml), 'internalId')
                if vm_id_node is None:
                    continue

                vm_id = vm_id_node.text
            else:
                if not vm.domain_xmlobject.has_element('metadata.internalId'):
                    continue

                vm_id = vm.domain_xmlobject.metadata.internalId.text_

            if vm_id:
                internal_ids.append(vm_id)

        # delete all vnc chains
        chains = tbl.children[:]
        for chain in chains:
            if 'vm' in chain.name and 'vnc' in chain.name:
                vm_internal_id = chain.name.split('-')[1]
                if vm_internal_id not in internal_ids:
                    ipt.delete_chain(chain.name)
                    logger.debug('deleted a stale VNC iptable chain[%s]' % chain.name)

        ipt.iptable_restore()


def e(parent, tag, value=None, attrib={}, usenamesapce = False):
    if usenamesapce:
        tag = '{%s}%s' % (ZS_XML_NAMESPACE, tag)

    el = etree.SubElement(parent, tag, attrib)
    if value:
        el.text = value
    return el


def find_namespace_node(root, path, name):
    ns = {'zs': ZS_XML_NAMESPACE}

    ps = path.split('.')
    cnode = root
    for p in ps:
        cnode = cnode.find(p)
        if cnode is None:
            return None

    return cnode.find('zs:%s' % name, ns)

def find_zstack_metadata_node(root, name):
    zs = find_namespace_node(root, 'metadata', 'zstack')
    if zs is None:
        return None

    return zs.find(name)

def find_domain_cdrom_address(domain_xml, target_dev):
    domain_xmlobject = xmlobject.loads(domain_xml)
    disks = domain_xmlobject.devices.get_children_nodes()['disk']
    for d in disks:
        if d.device_ != 'cdrom':
            continue
        if d.get_child_node('target').dev_ != target_dev:
            continue
        return d.get_child_node('address')
    return None

def compare_version(version1, version2):
    def normalize(v):
        return [int(x) for x in re.sub(r'(\.0+)*$','', v).split(".")]
    return cmp(normalize(version1), normalize(version2))

def get_libvirt_version():
    ret = shell.call('libvirtd --version')
    return ret.split()[-1]

LIBVIRT_VERSION = get_libvirt_version()
LIBVIRT_MAJOR_VERSION = LIBVIRT_VERSION.split('.')[0]

def is_namespace_used():
    return compare_version(LIBVIRT_VERSION, '1.3.3') >= 0

# Occasionally, libvirt might fail to list VM ...
def get_console_without_libvirt(vmUuid):
    output = bash.bash_o("""ps x | awk '/qemu[-]kvm.*%s/{print $1, index($0, " -vnc ")}'""" % vmUuid).splitlines()
    if len(output) != 1:
        return None, None

    pid, idx = output[0].split()
    proto = 'vnc' if int(idx) != 0 else 'spice'

    output = bash.bash_o("""lsof -p %s -aPi4 | awk '$8 == "TCP" { n=split($9,a,":"); print a[n] }'""" % pid).splitlines()
    if len(output) < 1:
        logger.warn("get_port_without_libvirt: no port found")
        return None, None
    return proto, min([int(port) for port in output])

class LibvirtEventManager(object):
    EVENT_DEFINED = "Defined"
    EVENT_UNDEFINED = "Undefined"
    EVENT_STARTED = "Started"
    EVENT_SUSPENDED = "Suspended"
    EVENT_RESUMED = "Resumed"
    EVENT_STOPPED = "Stopped"
    EVENT_SHUTDOWN = "Shutdown"

    event_strings = (
        EVENT_DEFINED,
        EVENT_UNDEFINED,
        EVENT_STARTED,
        EVENT_SUSPENDED,
        EVENT_RESUMED,
        EVENT_STOPPED,
        EVENT_SHUTDOWN
    )

    suspend_events = {}
    suspend_events[0] = "VIR_DOMAIN_EVENT_SUSPENDED_PAUSED"
    suspend_events[1] = "VIR_DOMAIN_EVENT_SUSPENDED_MIGRATED"
    suspend_events[2] = "VIR_DOMAIN_EVENT_SUSPENDED_IOERROR"
    suspend_events[3] = "VIR_DOMAIN_EVENT_SUSPENDED_WATCHDOG"
    suspend_events[4] = "VIR_DOMAIN_EVENT_SUSPENDED_RESTORED"
    suspend_events[5] = "VIR_DOMAIN_EVENT_SUSPENDED_FROM_SNAPSHOT"
    suspend_events[6] = "VIR_DOMAIN_EVENT_SUSPENDED_API_ERROR"
    suspend_events[7] = "VIR_DOMAIN_EVENT_SUSPENDED_POSTCOPY"
    suspend_events[8] = "VIR_DOMAIN_EVENT_SUSPENDED_POSTCOPY_FAILED"

    def __init__(self):
        self.stopped = False
        libvirt.virEventRegisterDefaultImpl()

        @thread.AsyncThread
        def run():
            logger.debug("virEventRunDefaultImpl starts")
            while not self.stopped:
                try:
                    if libvirt.virEventRunDefaultImpl() < 0:
                        logger.warn("virEventRunDefaultImpl quit with error")
                except:
                    content = traceback.format_exc()
                    logger.warn(content)

            logger.debug("virEventRunDefaultImpl stopped")

        run()

    def stop(self):
        self.stopped = True

    @staticmethod
    def event_to_string(index):
        return LibvirtEventManager.event_strings[index]

    @staticmethod
    def suspend_event_to_string(index):
        return LibvirtEventManager.suspend_events[index]


class LibvirtAutoReconnect(object):
    conn = libvirt.open('qemu:///system')

    if not conn:
        raise Exception('unable to get libvirt connection')

    evtMgr = LibvirtEventManager()

    libvirt_event_callbacks = {}

    def __init__(self, func):
        self.func = func
        self.exception = None

    @staticmethod
    def add_libvirt_callback(id, cb):
        cbs = LibvirtAutoReconnect.libvirt_event_callbacks.get(id, None)
        if cbs is None:
            cbs = []
            LibvirtAutoReconnect.libvirt_event_callbacks[id] = cbs
        cbs.append(cb)

    @staticmethod
    def register_libvirt_callbacks():
        def reboot_callback(conn, dom, opaque):
            cbs = LibvirtAutoReconnect.libvirt_event_callbacks.get(libvirt.VIR_DOMAIN_EVENT_ID_REBOOT)
            if not cbs:
                return

            for cb in cbs:
                try:
                    cb(conn, dom, opaque)
                except:
                    content = traceback.format_exc()
                    logger.warn(content)

        LibvirtAutoReconnect.conn.domainEventRegisterAny(None, libvirt.VIR_DOMAIN_EVENT_ID_REBOOT, reboot_callback,
                                                         None)

        def lifecycle_callback(conn, dom, event, detail, opaque):
            cbs = LibvirtAutoReconnect.libvirt_event_callbacks.get(libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE)
            if not cbs:
                return

            for cb in cbs:
                try:
                    cb(conn, dom, event, detail, opaque)
                except:
                    content = traceback.format_exc()
                    logger.warn(content)

        LibvirtAutoReconnect.conn.domainEventRegisterAny(None, libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                                                         lifecycle_callback, None)

        # NOTE: the keepalive doesn't work on some libvirtd even the versions are the same
        # the error is like "the caller doesn't support keepalive protocol; perhaps it's missing event loop implementation"

        # def start_keep_alive(_):
        #     try:
        #         LibvirtAutoReconnect.conn.setKeepAlive(5, 3)
        #         return True
        #     except Exception as e:
        #         logger.warn('unable to start libvirt keep-alive, %s' % str(e))
        #         return False
        #
        # if not linux.wait_callback_success(start_keep_alive, timeout=5, interval=0.5):
        #     raise Exception('unable to start libvirt keep-alive after 5 seconds, see the log for detailed error')

    @lock.lock('libvirt-reconnect')
    def _reconnect(self):
        def test_connection():
            try:
                LibvirtAutoReconnect.conn.getLibVersion()
                return None
            except libvirt.libvirtError as ex:
                return ex

        ex = test_connection()
        if not ex:
            # the connection is ok
            return

        logger.warn("the libvirt connection is broken, there is no safeway to auto-reconnect without fd leak, we"
                    " will ask the mgmt server to reconnect us after self quit")
        _stop_world()

        # old_conn = LibvirtAutoReconnect.conn
        # LibvirtAutoReconnect.conn = libvirt.open('qemu:///system')
        # if not LibvirtAutoReconnect.conn:
        #     raise Exception('unable to get a libvirt connection')
        #
        # for cid in LibvirtAutoReconnect.callback_id:
        #     logger.debug("remove libvirt event callback[id:%s]" % cid)
        #     old_conn.domainEventDeregisterAny(cid)
        #
        # # stop old event manager
        # LibvirtAutoReconnect.evtMgr.stop()
        # # create a new event manager
        # LibvirtAutoReconnect.evtMgr = LibvirtEventManager()
        # LibvirtAutoReconnect.register_libvirt_callbacks()
        #
        # # try to close the old connection anyway
        # try:
        #     old_conn.close()
        # except Exception as ee:
        #     logger.warn('unable to close an old libvirt exception, %s' % str(ee))
        # finally:
        #     del old_conn
        #
        # ex = test_connection()
        # if ex:
        #     # unable to reconnect, raise the error
        #     raise Exception('unable to get a libvirt connection, %s' % str(ex))
        #
        # logger.debug('successfully reconnected to the libvirt')

    def __call__(self, *args, **kwargs):
        try:
            return self.func(LibvirtAutoReconnect.conn)
        except libvirt.libvirtError as ex:
            err = str(ex)
            if 'client socket is closed' in err or 'Broken pipe' in err:
                logger.debug('socket to the libvirt is broken[%s], try reconnecting' % err)
                self._reconnect()
                return self.func(LibvirtAutoReconnect.conn)
            else:
                raise


class IscsiLogin(object):
    def __init__(self):
        self.server_hostname = None
        self.server_port = None
        self.target = None
        self.chap_username = None
        self.chap_password = None
        self.lun = 1

    @lock.lock('iscsiadm')
    def login(self):
        assert self.server_hostname, "hostname cannot be None"
        assert self.server_port, "port cannot be None"
        assert self.target, "target cannot be None"

        device_path = os.path.join('/dev/disk/by-path/', 'ip-%s:%s-iscsi-%s-lun-%s' % (
            self.server_hostname, self.server_port, self.target, self.lun))

        shell.call('iscsiadm -m discovery -t sendtargets -p %s:%s' % (self.server_hostname, self.server_port))

        if self.chap_username and self.chap_password:
            shell.call(
                'iscsiadm   --mode node  --targetname "%s"  -p %s:%s --op=update --name node.session.auth.authmethod --value=CHAP' % (
                    self.target, self.server_hostname, self.server_port))
            shell.call(
                'iscsiadm   --mode node  --targetname "%s"  -p %s:%s --op=update --name node.session.auth.username --value=%s' % (
                    self.target, self.server_hostname, self.server_port, self.chap_username))
            shell.call(
                'iscsiadm   --mode node  --targetname "%s"  -p %s:%s --op=update --name node.session.auth.password --value=%s' % (
                    self.target, self.server_hostname, self.server_port, self.chap_password))

        shell.call('iscsiadm  --mode node  --targetname "%s"  -p %s:%s --login' % (
            self.target, self.server_hostname, self.server_port))

        def wait_device_to_show(_):
            return os.path.exists(device_path)

        if not linux.wait_callback_success(wait_device_to_show, timeout=30, interval=0.5):
            raise Exception('ISCSI device[%s] is not shown up after 30s' % device_path)

        return device_path


class BlkIscsi(object):
    def __init__(self):
        self.is_cdrom = None
        self.volume_uuid = None
        self.chap_username = None
        self.chap_password = None
        self.device_letter = None
        self.addressBus = None
        self.addressUnit = None
        self.server_hostname = None
        self.server_port = None
        self.target = None
        self.lun = None

    def _login_portal(self):
        login = IscsiLogin()
        login.server_hostname = self.server_hostname
        login.server_port = self.server_port
        login.target = self.target
        login.chap_username = self.chap_username
        login.chap_password = self.chap_password
        return login.login()

    def to_xmlobject(self):
        device_path = self._login_portal()
        if self.is_cdrom:
            root = etree.Element('disk', {'type': 'block', 'device': 'cdrom'})
            e(root, 'driver', attrib={'name': 'qemu', 'type': 'raw', 'cache': 'none'})
            e(root, 'source', attrib={'dev': device_path})
            e(root, 'target', attrib={'dev': self.device_letter})
            if self.addressBus and self.addressUnit:
                e(root, 'address', None,{'type' : 'drive', 'bus' : self.addressBus, 'unit' : self.addressUnit})
        else:
            root = etree.Element('disk', {'type': 'block', 'device': 'lun'})
            e(root, 'driver', attrib={'name': 'qemu', 'type': 'raw', 'cache': 'none', 'discard':'unmap'})
            e(root, 'source', attrib={'dev': device_path})
            e(root, 'target', attrib={'dev': 'sd%s' % self.device_letter})
        return root

    @staticmethod
    @lock.lock('iscsiadm')
    def logout_portal(dev_path):
        if not os.path.exists(dev_path):
            return

        device = os.path.basename(dev_path)
        portal = device[3:device.find('-iscsi')]
        target = device[device.find('iqn'):device.find('-lun')]
        try:
            shell.call('iscsiadm  -m node  --targetname "%s" --portal "%s" --logout' % (target, portal))
        except Exception as e:
            logger.warn('failed to logout device[%s], %s' % (dev_path, str(e)))


class IsoCeph(object):
    def __init__(self):
        self.iso = None

    def to_xmlobject(self, target_dev, target_bus_type, bus=None, unit=None):
        disk = etree.Element('disk', {'type': 'network', 'device': 'cdrom'})
        source = e(disk, 'source', None, {'name': self.iso.path.lstrip('ceph:').lstrip('//'), 'protocol': 'rbd'})
        if self.iso.secretUuid:
            auth = e(disk, 'auth', attrib={'username': 'zstack'})
            e(auth, 'secret', attrib={'type': 'ceph', 'uuid': self.iso.secretUuid})
        for minfo in self.iso.monInfo:
            e(source, 'host', None, {'name': minfo.hostname, 'port': str(minfo.port)})

        e(disk, 'target', None, {'dev': target_dev, 'bus': target_bus_type})
        if bus and unit:
            e(disk, 'address', None, {'type': 'drive', 'bus': bus, 'unit': unit})
        e(disk, 'readonly', None)
        return disk


class BlkCeph(object):
    def __init__(self):
        self.volume = None
        self.dev_letter = None
        self.bus_type = None

    def to_xmlobject(self):
        disk = etree.Element('disk', {'type': 'network', 'device': 'disk'})
        source = e(disk, 'source', None,
                   {'name': self.volume.installPath.lstrip('ceph:').lstrip('//'), 'protocol': 'rbd'})
        if self.volume.secretUuid:
            auth = e(disk, 'auth', attrib={'username': 'zstack'})
            e(auth, 'secret', attrib={'type': 'ceph', 'uuid': self.volume.secretUuid})
        for minfo in self.volume.monInfo:
            e(source, 'host', None, {'name': minfo.hostname, 'port': str(minfo.port)})

        dev_format = Vm._get_disk_target_dev_format(self.bus_type)
        e(disk, 'target', None, {'dev': dev_format % self.dev_letter, 'bus': self.bus_type})
        return disk


class VirtioCeph(object):
    def __init__(self):
        self.volume = None
        self.dev_letter = None

    def to_xmlobject(self):
        disk = etree.Element('disk', {'type': 'network', 'device': 'disk'})
        source = e(disk, 'source', None,
                   {'name': self.volume.installPath.lstrip('ceph:').lstrip('//'), 'protocol': 'rbd'})
        if self.volume.secretUuid:
            auth = e(disk, 'auth', attrib={'username': 'zstack'})
            e(auth, 'secret', attrib={'type': 'ceph', 'uuid': self.volume.secretUuid})
        for minfo in self.volume.monInfo:
            e(source, 'host', None, {'name': minfo.hostname, 'port': str(minfo.port)})
        e(disk, 'target', None, {'dev': 'vd%s' % self.dev_letter, 'bus': 'virtio'})
        return disk


class VirtioSCSICeph(object):
    def __init__(self):
        self.volume = None
        self.dev_letter = None

    def to_xmlobject(self):
        disk = etree.Element('disk', {'type': 'network', 'device': 'disk'})
        source = e(disk, 'source', None,
                   {'name': self.volume.installPath.lstrip('ceph:').lstrip('//'), 'protocol': 'rbd'})
        if self.volume.secretUuid:
            auth = e(disk, 'auth', attrib={'username': 'zstack'})
            e(auth, 'secret', attrib={'type': 'ceph', 'uuid': self.volume.secretUuid})
        for minfo in self.volume.monInfo:
            e(source, 'host', None, {'name': minfo.hostname, 'port': str(minfo.port)})
        e(disk, 'target', None, {'dev': 'sd%s' % self.dev_letter, 'bus': 'scsi'})
        e(disk, 'wwn', self.volume.wwn)
        e(disk, 'address', None, {'type': 'drive', 'controller': '0', 'unit': Vm.get_device_unit(self.volume.deviceId)})
        if self.volume.shareable:
            e(disk, 'driver', None, {'name': 'qemu', 'type': 'raw', 'cache': 'none'})
            e(disk, 'shareable')
        return disk


class IsoFusionstor(object):
    def __init__(self):
        self.iso = None

    def to_xmlobject(self, target_dev, target_bus_type, bus=None, unit=None):
        protocol = lichbd.get_protocol()
        snap = self.iso.path.lstrip('fusionstor:').lstrip('//')
        path = self.iso.path.lstrip('fusionstor:').lstrip('//').split('@')[0]
        if protocol == 'lichbd':
            iqn = lichbd.lichbd_get_iqn()
            port = lichbd.lichbd_get_iscsiport()
            lichbd.makesure_qemu_img_with_lichbd()

            shellcmd = shell.ShellCmd(lichbdfactory.get_lichbd_version_class().LICHBD_CMD_POOL_CREATE+' %s -p iscsi' % path.split('/')[0])
            shellcmd(False)
            if shellcmd.return_code != 0 and shellcmd.return_code != 17:
                shellcmd.raise_error()

            shellcmd = shell.ShellCmd(
                'lich.snapshot --clone %s %s' % (os.path.join('/lichbd/', snap), os.path.join('/iscsi/', path)))
            shellcmd(False)
            if shellcmd.return_code != 0 and shellcmd.return_code != 17:
                shellcmd.raise_error()

            pool = path.split('/')[0]
            image = path.split('/')[1]
            # iqn:pool.volume/0
            path = '%s:%s.%s/0' % (iqn, pool, image)
            protocol = 'iscsi'
        elif protocol == 'sheepdog' or protocol == 'nbd':
            pass
        else:
            raise shell.ShellError('Do not supprot protocols, only supprot lichbd, sheepdog and nbd')

        disk = etree.Element('disk', {'type': 'network', 'device': 'cdrom'})
        source = e(disk, 'source', None, {'name': path, 'protocol': protocol})
        if protocol == 'iscsi':
            e(source, 'host', None, {'name': '127.0.0.1', 'port': '3260'})
        elif protocol == 'sheepdog':
            e(source, 'host', None, {'name': '127.0.0.1', 'port': '7000'})
        elif protocol == 'nbd':
            e(source, 'host', None, {'name': 'unix', 'port': '/tmp/nbd-socket'})
        e(disk, 'target', None, {'dev': target_dev, 'bus': target_bus_type})
        if bus and unit:
            e(disk, 'address', None, {'type': 'drive', 'bus': bus, 'unit': unit})
        e(disk, 'readonly', None)
        return disk


class BlkFusionstor(object):
    def __init__(self):
        self.volume = None
        self.dev_letter = None
        self.bus_type = None

    def to_xmlobject(self):
        protocol = lichbd.get_protocol()
        if protocol == 'lichbd':
            lichbd.makesure_qemu_img_with_lichbd()
        elif protocol == 'sheepdog' or protocol == 'nbd':
            pass
        else:
            raise shell.ShellError('Do not supprot protocols, only supprot lichbd, sheepdog and nbd')

        path = self.volume.installPath.lstrip('fusionstor:').lstrip('//')
        file_format = lichbd.lichbd_get_format(path)

        disk = etree.Element('disk', {'type': 'network', 'device': 'disk'})
        source = e(disk, 'source', None, {'name': path, 'protocol': protocol})
        if protocol == 'sheepdog':
            e(source, 'host', None, {'name': '127.0.0.1', 'port': '7000'})
        elif protocol == 'nbd':
            e(source, 'host', None, {'name': 'unix', 'port': '/tmp/nbd-socket'})

        dev_format = Vm._get_disk_target_dev_format(self.bus_type)
        e(disk, 'target', None, {'dev': dev_format % self.dev_letter, 'bus': self.bus_type})
        e(disk, 'driver', None, {'cache': 'none', 'name': 'qemu', 'io': 'native', 'type': file_format})
        return disk


class VirtioFusionstor(object):
    def __init__(self):
        self.volume = None
        self.dev_letter = None

    def to_xmlobject(self):
        protocol = lichbd.get_protocol()
        if protocol == 'lichbd':
            lichbd.makesure_qemu_img_with_lichbd()
        elif protocol == 'sheepdog' or protocol == 'nbd':
            pass
        else:
            raise shell.ShellError('Do not supprot protocols, only supprot lichbd, sheepdog and nbd')

        path = self.volume.installPath.lstrip('fusionstor:').lstrip('//')
        file_format = lichbd.lichbd_get_format(path)

        disk = etree.Element('disk', {'type': 'network', 'device': 'disk'})
        source = e(disk, 'source', None, {'name': path, 'protocol': protocol})
        if protocol == 'sheepdog':
            e(source, 'host', None, {'name': '127.0.0.1', 'port': '7000'})
        elif protocol == 'nbd':
            e(source, 'host', None, {'name': 'unix', 'port': '/tmp/nbd-socket'})
        e(disk, 'target', None, {'dev': 'vd%s' % self.dev_letter, 'bus': 'virtio'})
        e(disk, 'driver', None, {'cache': 'none', 'name': 'qemu', 'io': 'native', 'type': file_format})
        return disk


class VirtioSCSIFusionstor(object):
    def __init__(self):
        self.volume = None
        self.dev_letter = None

    def to_xmlobject(self):
        protocol = lichbd.get_protocol()
        if protocol == 'lichbd':
            lichbd.makesure_qemu_img_with_lichbd()
        elif protocol == 'sheepdog' or protocol == 'nbd':
            pass
        else:
            raise shell.ShellError('Protocol[%s] not supported, only support [lichbd, sheepdog, nbd]' % protocol)

        path = self.volume.installPath.lstrip('fusionstor:').lstrip('//')
        file_format = lichbd.lichbd_get_format(path)

        disk = etree.Element('disk', {'type': 'network', 'device': 'disk'})
        source = e(disk, 'source', None, {'name': path, 'protocol': protocol})
        if protocol == 'sheepdog':
            e(source, 'host', None, {'name': '127.0.0.1', 'port': '7000'})
        elif protocol == 'nbd':
            e(source, 'host', None, {'name': 'unix', 'port': '/tmp/nbd-socket'})

        e(disk, 'target', None, {'dev': 'sd%s' % self.dev_letter, 'bus': 'scsi'})
        e(disk, 'driver', None, {'cache': 'none', 'name': 'qemu', 'io': 'native', 'type': file_format})
        e(disk, 'wwn', self.volume.wwn)
        if self.volume.shareable:
            e(disk, 'shareable')
        return disk


class VirtioIscsi(object):
    def __init__(self):
        self.volume_uuid = None
        self.chap_username = None
        self.chap_password = None
        self.device_letter = None
        self.server_hostname = None
        self.server_port = None
        self.target = None
        self.lun = None

    def to_xmlobject(self):
        root = etree.Element('disk', {'type': 'network', 'device': 'disk'})
        e(root, 'driver', attrib={'name': 'qemu', 'type': 'raw', 'cache': 'none', 'discard':'unmap'})

        if self.chap_username and self.chap_password:
            auth = e(root, 'auth', attrib={'username': self.chap_username})
            e(auth, 'secret', attrib={'type': 'iscsi', 'uuid': self._get_secret_uuid()})

        source = e(root, 'source', attrib={'protocol': 'iscsi', 'name': '%s/%s' % (self.target, self.lun)})
        e(source, 'host', attrib={'name': self.server_hostname, 'port': self.server_port})
        e(root, 'target', attrib={'dev': 'sd%s' % self.device_letter, 'bus': 'scsi'})
        e(root, 'shareable')
        return root

    def _get_secret_uuid(self):
        root = etree.Element('secret', {'ephemeral': 'yes', 'private': 'yes'})
        e(root, 'description', self.volume_uuid)
        usage = e(root, 'usage', attrib={'type': 'iscsi'})
        e(usage, 'target', self.target)
        xml = etree.tostring(root)
        logger.debug('create secret for virtio-iscsi volume:\n%s\n' % xml)

        @LibvirtAutoReconnect
        def call_libvirt(conn):
            return conn.secretDefineXML(xml)

        secret = call_libvirt()
        secret.setValue(self.chap_password)
        return secret.UUIDString()


def get_vm_by_uuid(uuid, exception_if_not_existing=True, conn=None):
    try:
        # libvirt may not be able to find a VM when under a heavy workload, we re-try here
        @LibvirtAutoReconnect
        def call_libvirt(conn):
            return conn.lookupByName(uuid)

        @linux.retry(times=3, sleep_time=1)
        def retry_call_libvirt():
            if conn is None:
                return call_libvirt()
            else:
                return conn.lookupByName(uuid)

        vm = Vm.from_virt_domain(retry_call_libvirt())
        return vm
    except libvirt.libvirtError as e:
        error_code = e.get_error_code()
        if error_code == libvirt.VIR_ERR_NO_DOMAIN:
            if exception_if_not_existing:
                raise kvmagent.KvmError('unable to find vm[uuid:%s]' % uuid)
            else:
                return None

        err = 'error happened when looking up vm[uuid:%(uuid)s], libvirt error code: %(error_code)s, %(e)s' % locals()
        raise libvirt.libvirtError(err)

def get_vm_by_uuid_no_retry(uuid, exception_if_not_existing=True):
    try:
        # do not retry to fix create vm slow issue 4175
        @LibvirtAutoReconnect
        def call_libvirt(conn):
            return conn.lookupByName(uuid)

        vm = Vm.from_virt_domain(call_libvirt())
        return vm
    except libvirt.libvirtError as e:
        error_code = e.get_error_code()
        if error_code == libvirt.VIR_ERR_NO_DOMAIN:
            if exception_if_not_existing:
                raise kvmagent.KvmError('unable to find vm[uuid:%s]' % uuid)
            else:
                return None

        err = 'error happened when looking up vm[uuid:%(uuid)s], libvirt error code: %(error_code)s, %(e)s' % locals()
        raise libvirt.libvirtError(err)

def get_active_vm_uuids_states():
    @LibvirtAutoReconnect
    def call_libvirt(conn):
        return conn.listDomainsID()

    ids = call_libvirt()
    uuids_states = {}

    @LibvirtAutoReconnect
    def get_domain(conn):
        # i is for..loop's control variable
        # it's Python's local scope tricky
        try:
            return conn.lookupByID(i)
        except libvirt.libvirtError as ex:
            if ex.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return None
            raise ex

    for i in ids:
        domain = get_domain()
        if domain == None:
            continue

        uuid = domain.name()
        if uuid.startswith("guestfs-"):
            logger.debug("ignore the temp vm generate by guestfish.")
            continue
        if uuid == "ZStack Management Node VM":
            logger.debug("ignore the vm used for MN HA.")
            continue
        (state, _, _, _, _) = domain.info()
        state = Vm.power_state[state]
        # or use
        uuids_states[uuid] = state
    return uuids_states


def get_all_vm_states():
    return get_active_vm_uuids_states()


def get_running_vms():
    @LibvirtAutoReconnect
    def get_all_ids(conn):
        return conn.listDomainsID()

    ids = get_all_ids()
    vms = []

    @LibvirtAutoReconnect
    def get_domain(conn):
        try:
            return conn.lookupByID(i)
        except libvirt.libvirtError as ex:
            if ex.get_error_code() == libvirt.VIR_ERR_NO_DOMAIN:
                return None
            raise ex

    for i in ids:
        domain = get_domain()
        if domain == None:
            continue
        vm = Vm.from_virt_domain(domain)
        vms.append(vm)
    return vms


def get_cpu_memory_used_by_running_vms():
    runnings = get_running_vms()
    used_cpu = 0
    used_memory = 0
    for vm in runnings:
        used_cpu += vm.get_cpu_num()
        used_memory += vm.get_memory()

    return (used_cpu, used_memory)


def cleanup_stale_vnc_iptable_chains():
    VncPortIptableRule().delete_stale_chains()

def shared_block_to_file(sbkpath):
    return sbkpath.replace("sharedblock:/", "/dev")

class VmOperationJudger(object):
    def __init__(self, op):
        self.op = op
        self.expected_events = {}

        if self.op == VmPlugin.VM_OP_START:
            self.expected_events[LibvirtEventManager.EVENT_STARTED] = LibvirtEventManager.EVENT_STARTED
        elif self.op == VmPlugin.VM_OP_MIGRATE:
            self.expected_events[LibvirtEventManager.EVENT_STOPPED] = LibvirtEventManager.EVENT_STOPPED
        elif self.op == VmPlugin.VM_OP_STOP:
            self.expected_events[LibvirtEventManager.EVENT_STOPPED] = LibvirtEventManager.EVENT_STOPPED
        elif self.op == VmPlugin.VM_OP_DESTROY:
            self.expected_events[LibvirtEventManager.EVENT_STOPPED] = LibvirtEventManager.EVENT_STOPPED
        elif self.op == VmPlugin.VM_OP_REBOOT:
            self.expected_events[LibvirtEventManager.EVENT_STARTED] = LibvirtEventManager.EVENT_STARTED
            self.expected_events[LibvirtEventManager.EVENT_STOPPED] = LibvirtEventManager.EVENT_STOPPED
        elif self.op == VmPlugin.VM_OP_SUSPEND:
            self.expected_events[LibvirtEventManager.EVENT_SUSPENDED] = LibvirtEventManager.EVENT_SUSPENDED
        elif self.op == VmPlugin.VM_OP_RESUME:
            self.expected_events[LibvirtEventManager.EVENT_RESUMED] = LibvirtEventManager.EVENT_RESUMED
        else:
            raise Exception('unknown vm operation[%s]' % self.op)

    def remove_expected_event(self, evt):
        del self.expected_events[evt]
        return len(self.expected_events)

    def ignore_libvirt_events(self):
        if self.op == VmPlugin.VM_OP_START:
            return [LibvirtEventManager.EVENT_STARTED]
        elif self.op == VmPlugin.VM_OP_MIGRATE:
            return [LibvirtEventManager.EVENT_STOPPED, LibvirtEventManager.EVENT_UNDEFINED]
        elif self.op == VmPlugin.VM_OP_STOP:
            return [LibvirtEventManager.EVENT_STOPPED, LibvirtEventManager.EVENT_SHUTDOWN]
        elif self.op == VmPlugin.VM_OP_DESTROY:
            return [LibvirtEventManager.EVENT_STOPPED, LibvirtEventManager.EVENT_SHUTDOWN,
                    LibvirtEventManager.EVENT_UNDEFINED]
        elif self.op == VmPlugin.VM_OP_REBOOT:
            return [LibvirtEventManager.EVENT_STARTED, LibvirtEventManager.EVENT_STOPPED]
        else:
            raise Exception('unknown vm operation[%s]' % self.op)


class Vm(object):
    VIR_DOMAIN_NOSTATE = 0
    VIR_DOMAIN_RUNNING = 1
    VIR_DOMAIN_BLOCKED = 2
    VIR_DOMAIN_PAUSED = 3
    VIR_DOMAIN_SHUTDOWN = 4
    VIR_DOMAIN_SHUTOFF = 5
    VIR_DOMAIN_CRASHED = 6
    VIR_DOMAIN_PMSUSPENDED = 7

    VM_STATE_NO_STATE = 'NoState'
    VM_STATE_RUNNING = 'Running'
    VM_STATE_PAUSED = 'Paused'
    VM_STATE_SHUTDOWN = 'Shutdown'
    VM_STATE_CRASHED = 'Crashed'
    VM_STATE_SUSPENDED = 'Suspended'

    ALLOW_SNAPSHOT_STATE = (VM_STATE_RUNNING, VM_STATE_PAUSED, VM_STATE_SHUTDOWN)

    power_state = {
        VIR_DOMAIN_NOSTATE: VM_STATE_NO_STATE,
        VIR_DOMAIN_RUNNING: VM_STATE_RUNNING,
        VIR_DOMAIN_BLOCKED: VM_STATE_RUNNING,
        VIR_DOMAIN_PAUSED: VM_STATE_PAUSED,
        VIR_DOMAIN_SHUTDOWN: VM_STATE_SHUTDOWN,
        VIR_DOMAIN_SHUTOFF: VM_STATE_SHUTDOWN,
        VIR_DOMAIN_CRASHED: VM_STATE_CRASHED,
        VIR_DOMAIN_PMSUSPENDED: VM_STATE_SUSPENDED,
    }

    # IDE and SATA is not supported in aarch64/i440fx
    # so cdroms and volumes need to share sd[a-z]
    #
    # IDE is supported in x86_64/i440fx
    # so cdroms use hd[c-e]
    # virtio and virtioSCSI volumes share (sd[a-z] - sdc)
    if IS_AARCH64:
        DEVICE_LETTERS = 'abfghijklmnopqrstuvwxyz'
    else:
        DEVICE_LETTERS = 'abdefghijklmnopqrstuvwxyz'
    ISO_DEVICE_LETTERS = 'cde'

    @staticmethod
    def get_device_unit(device_id):
        if device_id >= len(Vm.DEVICE_LETTERS):
            err = "exceeds max disk limit, device id[%s], but only 0 ~ %d are allowed" % (device_id, len(Vm.DEVICE_LETTERS) - 1)
            logger.warn(err)
            raise kvmagent.KvmError(err)

        # aarch64 use device_letter as address->unit
        # e.g. sda -> unit 0    sdf -> unit 5
        if IS_AARCH64:
            return str(ord(Vm.DEVICE_LETTERS[device_id]) - ord(Vm.DEVICE_LETTERS[0]))

        # x86_64 use device_id as address->unit
        return str(device_id)

    @staticmethod
    def get_iso_device_unit(device_id):
        if device_id >= len(Vm.ISO_DEVICE_LETTERS):
            err = "exceeds max iso limit, device id[%s], but only 0 ~ %d are allowed" % (device_id, len(Vm.ISO_DEVICE_LETTERS) - 1)
            logger.warn(err)
            raise kvmagent.KvmError(err)
        return str(ord(Vm.ISO_DEVICE_LETTERS[device_id]) - ord(Vm.DEVICE_LETTERS[0]))

    timeout_object = linux.TimeoutObject()

    def __init__(self):
        self.uuid = None
        self.domain_xmlobject = None
        self.domain_xml = None
        self.domain = None
        self.state = None

    def wait_for_state_change(self, state):
        try:
            self.refresh()
        except Exception as e:
            if not state:
                return True
            raise e

        return self.state == state

    def get_cpu_num(self):
        cpuNum = self.domain_xmlobject.vcpu.current__
        if cpuNum:
            return int(cpuNum)
        else:
            return int(self.domain_xmlobject.vcpu.text_)

    def get_cpu_speed(self):
        cputune = self.domain_xmlobject.get_child_node('cputune')
        if cputune:
            return int(cputune.shares.text_) / self.get_cpu_num()
        else:
            # TODO: return system cpu capacity
            return 512

    def get_memory(self):
        return long(self.domain_xmlobject.currentMemory.text_) * 1024

    def get_name(self):
        return self.domain_xmlobject.description.text_

    def refresh(self):
        (state, _, _, _, _) = self.domain.info()
        self.state = self.power_state[state]
        self.domain_xml = self.domain.XMLDesc(0)
        self.domain_xmlobject = xmlobject.loads(self.domain_xml)
        self.uuid = self.domain_xmlobject.name.text_

    def is_alive(self):
        try:
            self.domain.info()
            return True
        except:
            return False

    def _wait_for_vm_running(self, timeout=60):
        if not linux.wait_callback_success(self.wait_for_state_change, self.VM_STATE_RUNNING, interval=0.5,
                                           timeout=timeout):
            raise kvmagent.KvmError('unable to start vm[uuid:%s, name:%s], vm state is not changing to '
                                    'running after %s seconds' % (self.uuid, self.get_name(), timeout))

        vnc_port = self.get_console_port()

        def wait_vnc_port_open(_):
            cmd = shell.ShellCmd('netstat -na | grep ":%s" > /dev/null' % vnc_port)
            cmd(is_exception=False)
            return cmd.return_code == 0

        if not linux.wait_callback_success(wait_vnc_port_open, None, interval=0.5, timeout=30):
            raise kvmagent.KvmError("unable to start vm[uuid:%s, name:%s]; its vnc port does"
                                    " not open after 30 seconds" % (self.uuid, self.get_name()))

    def _wait_for_vm_paused(self, timeout=60):
        if not linux.wait_callback_success(self.wait_for_state_change, self.VM_STATE_PAUSED, interval=0.5,
                                           timeout=timeout):
            raise kvmagent.KvmError('unable to start vm[uuid:%s, name:%s], vm state is not changing to '
                                    'paused after %s seconds' % (self.uuid, self.get_name(), timeout))

    def reboot(self, cmd):
        self.stop(timeout=cmd.timeout)

        # set boot order
        boot_dev = []
        for bdev in cmd.bootDev:
            xo = xmlobject.XmlObject('boot')
            xo.put_attr('dev', bdev)
            boot_dev.append(xo)

        self.domain_xmlobject.os.replace_node('boot', boot_dev)
        self.domain_xml = self.domain_xmlobject.dump()

        self.start(cmd.timeout)

    def start(self, timeout=60, create_paused=False):
        # TODO: 1. enable hair_pin mode
        logger.debug('creating vm:\n%s' % self.domain_xml)

        @LibvirtAutoReconnect
        def define_xml(conn):
            return conn.defineXML(self.domain_xml)

        flag = (0, libvirt.VIR_DOMAIN_START_PAUSED)[create_paused]
        domain = define_xml()
        self.domain = domain
        self.domain.createWithFlags(flag)
        if create_paused:
            self._wait_for_vm_paused(timeout)
        else:
            self._wait_for_vm_running(timeout)

    def stop(self, graceful=True, timeout=5, undefine=True):
        def cleanup_addons():
            for chan in self.domain_xmlobject.devices.get_child_node_as_list('channel'):
                if chan.type_ == 'unix':
                    path = chan.source.path_
                    linux.rm_file_force(path)

        def loop_shutdown(_):
            try:
                self.domain.shutdown()
            except:
                # domain has been shut down
                pass

            try:
                return self.wait_for_state_change(self.VM_STATE_SHUTDOWN)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                    return True
                else:
                    raise

        def iscsi_cleanup():
            disks = self.domain_xmlobject.devices.get_child_node_as_list('disk')

            for disk in disks:
                if disk.type_ == 'block' and disk.device_ == 'lun':
                    BlkIscsi.logout_portal(disk.source.dev_)

        def loop_undefine(_):
            if not undefine:
                return True

            if not self.is_alive():
                return True

            def force_undefine():
                try:
                    self.domain.undefine()
                except:
                    logger.warn('cannot undefine the VM[uuid:%s]' % self.uuid)
                    pid = linux.find_process_by_cmdline(['qemu', self.uuid])
                    if pid:
                        # force to kill the VM
                        shell.call('kill -9 %s' % pid)

            try:
                self.domain.undefineFlags(
                    libvirt.VIR_DOMAIN_UNDEFINE_MANAGED_SAVE | libvirt.VIR_DOMAIN_UNDEFINE_SNAPSHOTS_METADATA | libvirt.VIR_DOMAIN_UNDEFINE_NVRAM)
            except libvirt.libvirtError as ex:
                logger.warn('undefine domain[%s] failed: %s' % (self.uuid, str(ex)))
                force_undefine()

            return self.wait_for_state_change(None)

        def loop_destroy(_):
            try:
                self.domain.destroy()
            except:
                # domain has been destroyed
                pass

            try:
                return self.wait_for_state_change(self.VM_STATE_SHUTDOWN)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                    return True
                else:
                    raise

        do_destroy = True
        if graceful:
            if linux.wait_callback_success(loop_shutdown, None, timeout=60):
                do_destroy = False

        iscsi_cleanup()

        if do_destroy:
            if not linux.wait_callback_success(loop_destroy, None, timeout=60):
                logger.warn('failed to destroy vm, timeout after 60 secs')
                raise kvmagent.KvmError('failed to stop vm, timeout after 60 secs')

        cleanup_addons()

        vm = get_vm_by_uuid(self.uuid, False)
        if vm:
            # undefine domain only if it is persistent
            if not self.domain.isPersistent():
                return
        else:
            return

        if not linux.wait_callback_success(loop_undefine, None, timeout=60):
            logger.warn('failed to undefine vm, timeout after 60 secs')
            raise kvmagent.KvmError('failed to stop vm, timeout after 60 secs')

    def destroy(self):
        self.stop(graceful=False)

    def pause(self, timeout=5):
        def loop_suspend(_):
            try:
                self.domain.suspend()
            except:
                pass
            try:
                return self.wait_for_state_change(self.VM_STATE_PAUSED)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                    return True
                else:
                    raise

        if not linux.wait_callback_success(loop_suspend, None, timeout=10):
            raise kvmagent.KvmError('failed to suspend vm ,timeout after 10 secs')

    def resume(self, timeout=5):
        def loop_resume(_):
            try:
                self.domain.resume()
            except:
                pass
            try:
                return self.wait_for_state_change(self.VM_STATE_RUNNING)
            except libvirt.libvirtError as ex:
                error_code = ex.get_error_code()
                if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                    return True
                else:
                    raise

        if not linux.wait_callback_success(loop_resume, None, timeout=60):
            raise kvmagent.KvmError('failed to resume vm ,timeout after 60 secs')

    def harden_console(self, mgmt_ip):
        if is_namespace_used():
            id_node = find_zstack_metadata_node(etree.fromstring(self.domain_xml), 'internalId')
            id = id_node.text
        else:
            id = self.domain_xmlobject.metadata.internalId.text_

        vir = VncPortIptableRule()
        vir.vm_internal_id = id
        vir.delete()

        vir.host_ip = mgmt_ip
        vir.port = self.get_console_port()
        vir.apply()

    def get_console_port(self):
        for g in self.domain_xmlobject.devices.get_child_node_as_list('graphics'):
            if g.type_ == 'vnc' or g.type_ == 'spice':
                return g.port_

    def get_console_protocol(self):
        for g in self.domain_xmlobject.devices.get_child_node_as_list('graphics'):
            if g.type_ == 'vnc' or g.type_ == 'spice':
                return g.type_

        raise kvmagent.KvmError('no vnc console defined for vm[uuid:%s]' % self.uuid)

    def attach_data_volume(self, volume, addons):
        self._wait_vm_run_until_seconds(10)
        self.timeout_object.wait_until_object_timeout('detach-volume-%s' % self.uuid)
        self._attach_data_volume(volume, addons)
        self.timeout_object.put('attach-volume-%s' % self.uuid, timeout=10)

    @staticmethod
    def set_volume_qos(addons, volumeUuid, volume_xml_obj):
        if not addons:
            return

        for key in ["VolumeQos", "VolumeReadQos", "VolumeWriteQos"]:
            vol_qos = addons[key]
            if not vol_qos:
                continue

            qos = vol_qos[volumeUuid]
            if not qos:
                continue
            if not qos.totalBandwidth and not qos.totalIops:
                continue

            mode = None
            if key == 'VolumeQos':
                mode = "total"
            elif key == 'VolumeReadQos':
                mode = "read"
            elif key == 'VolumeWriteQos':
                mode = "write"

            iotune = e(volume_xml_obj, 'iotune')
            if qos.totalBandwidth:
                virsh_key = "%s_bytes_sec" % mode
                e(iotune, virsh_key, str(qos.totalBandwidth))
            if qos.totalIops:
                virsh_key = "%_iops_sec" % mode
                e(iotune, virsh_key, str(qos.totalIops))

    def _attach_data_volume(self, volume, addons):
        if volume.deviceId >= len(self.DEVICE_LETTERS):
            err = "vm[uuid:%s] exceeds max disk limit, device id[%s], but only 0 ~ %d are allowed" % (self.uuid, volume.deviceId, len(self.DEVICE_LETTERS) - 1)
            logger.warn(err)
            raise kvmagent.KvmError(err)

        def volume_native_aio(volume_xml_obj):
            if not addons:
                return

            vol_aio = addons['NativeAio']
            if not vol_aio:
                return

            drivers = volume_xml_obj.getiterator("driver")
            if drivers is None or len(drivers) == 0:
                return

            drivers[0].set("io", "native")

        def filebased_volume():
            disk = etree.Element('disk', attrib={'type': 'file', 'device': 'disk'})
            e(disk, 'driver', None, {'name': 'qemu', 'type': linux.get_img_fmt(volume.installPath), 'cache': volume.cacheMode})
            e(disk, 'source', None, {'file': volume.installPath})

            if volume.shareable:
                e(disk, 'shareable')

            if volume.useVirtioSCSI:
                e(disk, 'target', None, {'dev': 'sd%s' % dev_letter, 'bus': 'scsi'})
                e(disk, 'wwn', volume.wwn)
                e(disk, 'address', None, {'type': 'drive', 'controller': '0', 'unit': self.get_device_unit(volume.deviceId)})
            elif volume.useVirtio:
                e(disk, 'target', None, {'dev': 'vd%s' % self.DEVICE_LETTERS[volume.deviceId], 'bus': 'virtio'})
            else:
                bus_type = self._get_controller_type()
                dev_format = Vm._get_disk_target_dev_format(bus_type)
                e(disk, 'target', None, {'dev': dev_format % dev_letter, 'bus': bus_type})

            Vm.set_volume_qos(addons, volume.volumeUuid, disk)
            volume_native_aio(disk)
            return etree.tostring(disk)

        def scsilun_volume():
            disk = etree.Element('disk', attrib={'type': 'block', 'device': 'lun', 'sgio': 'unfiltered'})
            e(disk, 'driver', None,
              {'name': 'qemu', 'type': 'raw'})
            e(disk, 'source', None, {'dev': volume.installPath})
            e(disk, 'target', None, {'dev': 'sd%s' % dev_letter, 'bus': 'scsi'})
            #NOTE(weiw): scsi lun not support aio or qos
            return etree.tostring(disk)

        def iscsibased_volume():
            def virtio_iscsi():
                vi = VirtioIscsi()
                portal, vi.target, vi.lun = volume.installPath.lstrip('iscsi://').split('/')
                vi.server_hostname, vi.server_port = portal.split(':')
                vi.device_letter = dev_letter
                vi.volume_uuid = volume.volumeUuid
                vi.chap_username = volume.chapUsername
                vi.chap_password = volume.chapPassword
                Vm.set_volume_qos(addons, volume.volumeUuid, vi)
                volume_native_aio(vi)
                return etree.tostring(vi.to_xmlobject())

            def blk_iscsi():
                bi = BlkIscsi()
                portal, bi.target, bi.lun = volume.installPath.lstrip('iscsi://').split('/')
                bi.server_hostname, bi.server_port = portal.split(':')
                bi.device_letter = dev_letter
                bi.volume_uuid = volume.volumeUuid
                bi.chap_username = volume.chapUsername
                bi.chap_password = volume.chapPassword
                Vm.set_volume_qos(addons, volume.volumeUuid, bi)
                volume_native_aio(bi)
                return etree.tostring(bi.to_xmlobject())

            if volume.useVirtio:
                return virtio_iscsi()
            else:
                return blk_iscsi()

        def ceph_volume():
            def virtoio_ceph():
                vc = VirtioCeph()
                vc.volume = volume
                vc.dev_letter = dev_letter
                xml_obj = vc.to_xmlobject()
                Vm.set_volume_qos(addons, volume.volumeUuid, xml_obj)
                volume_native_aio(xml_obj)
                return etree.tostring(xml_obj)

            def blk_ceph():
                ic = BlkCeph()
                ic.volume = volume
                ic.dev_letter = dev_letter
                ic.bus_type = self._get_controller_type()
                xml_obj = ic.to_xmlobject()
                Vm.set_volume_qos(addons, volume.volumeUuid, xml_obj)
                volume_native_aio(xml_obj)
                return etree.tostring(xml_obj)

            def virtio_scsi_ceph():
                vsc = VirtioSCSICeph()
                vsc.volume = volume
                vsc.dev_letter = dev_letter
                xml_obj = vsc.to_xmlobject()
                Vm.set_volume_qos(addons, volume.volumeUuid, xml_obj)
                volume_native_aio(xml_obj)
                return etree.tostring(xml_obj)

            if volume.useVirtioSCSI:
                return virtio_scsi_ceph()
            else:
                if volume.useVirtio:
                    return virtoio_ceph()
                else:
                    return blk_ceph()

        def fusionstor_volume():
            def virtoio_fusionstor():
                vc = VirtioFusionstor()
                vc.volume = volume
                vc.dev_letter = dev_letter
                xml_obj = vc.to_xmlobject()
                Vm.set_volume_qos(addons, volume.volumeUuid, xml_obj)
                volume_native_aio(xml_obj)
                return etree.tostring(xml_obj)

            def blk_fusionstor():
                ic = BlkFusionstor()
                ic.volume = volume
                ic.dev_letter = dev_letter
                ic.bus_type = self._get_controller_type()
                xml_obj = ic.to_xmlobject()
                Vm.set_volume_qos(addons, volume.volumeUuid, xml_obj)
                volume_native_aio(xml_obj)
                return etree.tostring(xml_obj)

            def virtio_scsi_fusionstor():
                vsc = VirtioSCSIFusionstor()
                vsc.volume = volume
                vsc.dev_letter = dev_letter
                xml_obj = vsc.to_xmlobject()
                Vm.set_volume_qos(addons, volume.volumeUuid, xml_obj)
                volume_native_aio(xml_obj)
                return etree.tostring(xml_obj)

            if volume.useVirtioSCSI:
                return virtio_scsi_fusionstor()
            else:
                if volume.useVirtio:
                    return virtoio_fusionstor()
                else:
                    return blk_fusionstor()

        def block_volume():
            def blk():
                disk = etree.Element('disk', {'type': 'block', 'device': 'disk', 'snapshot': 'external'})
                e(disk, 'driver', None,
                  {'name': 'qemu', 'type': 'raw', 'cache': 'none', 'io': 'native'})
                e(disk, 'source', None, {'dev': volume.installPath})

                if volume.useVirtioSCSI:
                    e(disk, 'target', None, {'dev': 'sd%s' % dev_letter, 'bus': 'scsi'})
                    e(disk, 'wwn', volume.wwn)
                else:
                    e(disk, 'target', None, {'dev': 'vd%s' % dev_letter, 'bus': 'virtio'})

                return etree.tostring(disk)
            return blk()

        dev_letter = self._get_device_letter(volume, addons)
        if volume.deviceType == 'iscsi':
            xml = iscsibased_volume()
        elif volume.deviceType == 'file':
            xml = filebased_volume()
        elif volume.deviceType == 'ceph':
            xml = ceph_volume()
        elif volume.deviceType == 'fusionstor':
            xml = fusionstor_volume()
        elif volume.deviceType == 'scsilun':
            xml = scsilun_volume()
        elif volume.deviceType == 'block':
            xml = block_volume()
        else:
            raise Exception('unsupported volume deviceType[%s]' % volume.deviceType)

        logger.debug('attaching volume[%s] to vm[uuid:%s]:\n%s' % (volume.installPath, self.uuid, xml))
        try:
            # libvirt has a bug that if attaching volume just after vm created, it likely fails. So we retry three time here
            @linux.retry(times=3, sleep_time=5)
            def attach():
                def wait_for_attach(_):
                    me = get_vm_by_uuid(self.uuid)
                    disk, _ = me._get_target_disk(volume, is_exception=False)

                    if not disk:
                        logger.debug('volume[%s] is still in process of attaching, wait it' % volume.installPath)
                    return bool(disk)

                try:
                    self.domain.attachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)

                    if not linux.wait_callback_success(wait_for_attach, None, 5, 1):
                        raise Exception("cannot attach a volume[uuid: %s] to the vm[uuid: %s];"
                                        "it's still not attached after 5 seconds" % (volume.volumeUuid, self.uuid))
                except:
                    # check one more time
                    if not wait_for_attach(None):
                        raise

            attach()

        except libvirt.libvirtError as ex:
            err = str(ex)
            if 'Duplicate ID' in err:
                err = ('unable to attach the volume[%s] to vm[uuid: %s], %s. This is a KVM issue, please reboot'
                       ' the VM and try again' % (volume.volumeUuid, self.uuid, err))
            elif 'No more available PCI slots' in err:
                err = ('vm[uuid: %s] has no more PCI slots for volume[%s]. This is a Libvirt issue, please reboot'
                       ' the VM and try again' % (self.uuid, volume.volumeUuid))
            else:
                err = 'unable to attach the volume[%s] to vm[uuid: %s], %s.' % (volume.volumeUuid, self.uuid, err)
            logger.warn(linux.get_exception_stacktrace())
            raise kvmagent.KvmError(err)

    def _get_device_letter(self, volume, addons):
        default_letter = Vm.DEVICE_LETTERS[volume.deviceId]
        if not volume.useVirtioSCSI:
            return default_letter

        # usually, device_letter_index equals device_id, but reversed when volume use VirtioSCSI because of ZSTAC-9641
        # so when attach SCSI volume again after detached it, device_letter should be same as origin name,
        # otherwise it will fail for duplicate device name.

        def get_reversed_disks():
            results = {}
            for vol in addons.attachedDataVolumes:
                _, disk_name = self._get_target_disk(vol)
                if disk_name and disk_name[-1] != Vm.DEVICE_LETTERS[vol.deviceId]:
                    results[disk_name[-1]] = vol.deviceId

            return results

        # {actual_dev_letter: device_id_in_db}
        # type: dict[str, int]
        reversed_disks = get_reversed_disks()
        if default_letter not in reversed_disks.keys():
            return default_letter
        else:
            # letter has been occupied, so return reversed letter
            logger.debug("reversed disk name: %s" % reversed_disks)
            return Vm.DEVICE_LETTERS[reversed_disks[default_letter]]

    def detach_data_volume(self, volume):
        self._wait_vm_run_until_seconds(10)
        self.timeout_object.wait_until_object_timeout('attach-volume-%s' % self.uuid)
        self._detach_data_volume(volume)
        self.timeout_object.put('detach-volume-%s' % self.uuid, timeout=10)

    def _detach_data_volume(self, volume):
        assert volume.deviceId != 0, 'how can root volume gets detached???'

        target_disk, disk_name = self._get_target_disk(volume)
        if not target_disk:
            raise kvmagent.KvmError('unable to find data volume[%s] on vm[uuid:%s]' % (disk_name, self.uuid))

        xmlstr = target_disk.dump()
        logger.debug('detaching volume from vm[uuid:%s]:\n%s' % (self.uuid, xmlstr))
        try:
            # libvirt has a bug that if detaching volume just after vm created, it likely fails. So we retry three time here
            @linux.retry(times=3, sleep_time=5)
            def detach():
                def wait_for_detach(_):
                    me = get_vm_by_uuid(self.uuid)
                    disk, _ = me._get_target_disk(volume, is_exception=False)

                    if disk:
                        logger.debug('volume[%s] is still in process of detaching, wait for it' % volume.installPath)

                    return not bool(disk)

                try:
                    self.domain.detachDeviceFlags(xmlstr, libvirt.VIR_DOMAIN_AFFECT_LIVE)

                    if not linux.wait_callback_success(wait_for_detach, None, 5, 1):
                        raise Exception("unable to detach the volume[uuid:%s] from the vm[uuid:%s];"
                                        "it's still attached after 5 seconds" %
                                        (volume.volumeUuid, self.uuid))
                except:
                    # check one more time
                    if not wait_for_detach(None):
                        raise

            detach()

            def logout_iscsi():
                BlkIscsi.logout_portal(target_disk.source.dev_)

            if volume.deviceType == 'iscsi':
                if not volume.useVirtio:
                    logout_iscsi()


        except libvirt.libvirtError as ex:
            vm = get_vm_by_uuid(self.uuid)
            logger.warn('vm dump: %s' % vm.domain_xml)
            logger.warn(linux.get_exception_stacktrace())
            raise kvmagent.KvmError(
                'unable to detach volume[%s] from vm[uuid:%s], %s' % (volume.installPath, self.uuid, str(ex)))

    def _get_back_file(self, volume):
        ret = shell.call('qemu-img info %s' % volume)
        for l in ret.split('\n'):
            l = l.strip(' \n\t\r')
            if l == '':
                continue

            k, v = l.split(':')
            if k == 'backing file':
                return v.strip()

        return None

    def _get_backfile_chain(self, current):
        back_files = []

        def get_back_files(volume):
            back_file = self._get_back_file(volume)
            if back_file is None:
                return

            back_files.append(back_file)
            get_back_files(back_file)

        get_back_files(current)
        return back_files

    # NOTE: code from Openstack nova
    def _wait_for_block_job(self, disk_path, abort_on_error=False,
                            wait_for_job_clean=False):
        """Wait for libvirt block job to complete.

        Libvirt may return either cur==end or an empty dict when
        the job is complete, depending on whether the job has been
        cleaned up by libvirt yet, or not.

        :returns: True if still in progress
                  False if completed
        """

        status = self.domain.blockJobInfo(disk_path, 0)
        if status == -1 and abort_on_error:
            raise kvmagent.KvmError('libvirt error while requesting blockjob info.')

        try:
            cur = status.get('cur', 0)
            end = status.get('end', 0)
        except Exception as e:
            logger.warn(linux.get_exception_stacktrace())
            return False

        if wait_for_job_clean:
            job_ended = not status
        else:
            job_ended = cur == end

        return not job_ended

    def _get_target_disk(self, volume, is_exception=True):
        if volume.installPath.startswith('sharedblock'):
            volume.installPath = shared_block_to_file(volume.installPath)

        for disk in self.domain_xmlobject.devices.get_child_node_as_list('disk'):
            if not xmlobject.has_element(disk, 'source'):
                continue

            if volume.deviceType == 'iscsi':
                if volume.useVirtio:
                    if disk.source.name__ and disk.source.name_ in volume.installPath:
                        return disk, disk.target.dev_
                else:
                    if disk.source.dev__ and volume.volumeUuid in disk.source.dev_:
                        return disk, disk.target.dev_
            elif volume.deviceType == 'file':
                if disk.source.file__ and disk.source.file_ == volume.installPath:
                    return disk, disk.target.dev_
            elif volume.deviceType == 'ceph':
                if disk.source.name__ and disk.source.name_ in volume.installPath:
                    return disk, disk.target.dev_
            elif volume.deviceType == 'fusionstor':
                if disk.source.name__ and disk.source.name_ in volume.installPath:
                    return disk, disk.target.dev_
            elif volume.deviceType == 'scsilun':
                if disk.source.dev__ and volume.installPath in disk.source.dev_:
                    return disk, disk.target.dev_
            elif volume.deviceType == 'block':
                if disk.source.dev__ and disk.source.dev_ in volume.installPath:
                    return disk, disk.target.dev_
        if not is_exception:
            return None, None

        logger.debug('%s is not found on the vm[uuid:%s]' % (volume.installPath, self.uuid))
        raise kvmagent.KvmError('unable to find volume[installPath:%s] on vm[uuid:%s]' % (volume.installPath, self.uuid))

    def resize_volume(self, volume, device_type, size):
        device_id = volume.deviceId
        target_disk, disk_name = self._get_target_disk(volume)

        alias_name = target_disk.alias.name_

        r, o, e = bash.bash_roe("virsh qemu-monitor-command %s block_resize drive-%s %sB --hmp"
                                % (self.uuid, alias_name, size))

        logger.debug("resize volume[%s] of vm[%s]" % (alias_name, self.uuid))
        if r != 0:
            raise kvmagent.KvmError(
                'unable to resize volume[id:{1}] of vm[uuid:{0}] because {2}'.format(device_id, self.uuid, e))

    def take_live_volumes_delta_snapshots(self, vs_structs):
        """
        :type vs_structs: list[VolumeSnapshotJobStruct]
        :rtype: list[VolumeSnapshotResultStruct]
        """
        disk_names = []
        return_structs = []

        snapshot = etree.Element('domainsnapshot')
        disks = e(snapshot, 'disks')
        logger.debug(snapshot)

        if len(vs_structs) == 0:
            return return_structs

        def get_size(install_path):
            """
            :rtype: long
            """
            size = linux.get_local_file_disk_usage(install_path)
            if size is None or size == 0:
                size = linux.qcow2_virtualsize(install_path)
            return size

        logger.debug(vs_structs)
        for vs_struct in vs_structs:
            if vs_struct.live is False or vs_struct.full is True:
                raise kvmagent.KvmError("volume %s is not live or full snapshot specified, "
                                        "can not proceed")
            target_disk, disk_name = self._get_target_disk(vs_struct.volume)
            if target_disk is None:
                logger.debug("can not find %s" % vs_struct.volume.deviceId)
                continue

            snapshot_dir = os.path.dirname(vs_struct.installPath)
            if not os.path.exists(snapshot_dir):
                os.makedirs(snapshot_dir)

            disk_names.append(disk_name)
            d = e(disks, 'disk', None, attrib={'name': disk_name, 'snapshot': 'external', 'type': 'file'})
            e(d, 'source', None, attrib={'file': vs_struct.installPath})
            e(d, 'driver', None, attrib={'type': 'qcow2'})
            return_structs.append(VolumeSnapshotResultStruct(
                vs_struct.volumeUuid,
                target_disk.source.file_,
                vs_struct.installPath,
                get_size(target_disk.source.file_)))

        for disk in self.domain_xmlobject.devices.get_child_node_as_list('disk'):
            if disk.target.dev_ not in disk_names:
                e(disks, 'disk', None, attrib={'name': disk.target.dev_, 'snapshot': 'no'})

        xml = etree.tostring(snapshot)
        logger.debug('creating live snapshot for vm[uuid:{0}] volumes[id:{1}]:\n{2}'.format(self.uuid, disk_names, xml))
        snap_flags = libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY | \
                     libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA | \
                     libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_ATOMIC

        try:
            self.domain.snapshotCreateXML(xml, snap_flags)
            return return_structs
        except libvirt.libvirtError as ex:
            logger.warn(linux.get_exception_stacktrace())
            raise kvmagent.KvmError(
                'unable to take live snapshot of vm[uuid:{0}] volumes[id:{1}], {2}'.format(self.uuid, disk_names, str(ex)))

    def take_volume_snapshot(self, volume, install_path, full_snapshot=False):
        device_id = volume.deviceId
        target_disk, disk_name = self._get_target_disk(volume)
        snapshot_dir = os.path.dirname(install_path)
        if not os.path.exists(snapshot_dir):
            os.makedirs(snapshot_dir)

        previous_install_path = target_disk.source.file_
        back_file_len = len(self._get_backfile_chain(previous_install_path))
        # for RHEL, base image's back_file_len == 1; for ubuntu back_file_len == 0
        first_snapshot = full_snapshot and (back_file_len == 1 or back_file_len == 0)

        def take_delta_snapshot():
            snapshot = etree.Element('domainsnapshot')
            disks = e(snapshot, 'disks')
            d = e(disks, 'disk', None, attrib={'name': disk_name, 'snapshot': 'external', 'type': 'file'})
            e(d, 'source', None, attrib={'file': install_path})
            e(d, 'driver', None, attrib={'type': 'qcow2'})

            # QEMU 2.3 default create snapshots on all devices
            # but we only need for one
            for disk in self.domain_xmlobject.devices.get_child_node_as_list('disk'):
                if disk.target.dev_ != disk_name:
                    e(disks, 'disk', None, attrib={'name': disk.target.dev_, 'snapshot': 'no'})

            xml = etree.tostring(snapshot)
            logger.debug('creating snapshot for vm[uuid:{0}] volume[id:{1}]:\n{2}'.format(self.uuid, device_id, xml))
            snap_flags = libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY | libvirt.VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA

            try:
                self.domain.snapshotCreateXML(xml, snap_flags)
                return previous_install_path, install_path
            except libvirt.libvirtError as ex:
                logger.warn(linux.get_exception_stacktrace())
                raise kvmagent.KvmError(
                    'unable to take snapshot of vm[uuid:{0}] volume[id:{1}], {2}'.format(self.uuid, device_id, str(ex)))

        def take_full_snapshot():
            self.block_stream_disk(volume)
            return take_delta_snapshot()

        if first_snapshot:
            # the first snapshot is always full snapshot
            # at this moment, delta snapshot returns the original volume as full snapshot
            return take_delta_snapshot()

        if full_snapshot:
            return take_full_snapshot()
        else:
            return take_delta_snapshot()

    def block_stream_disk(self, volume):
        target_disk, disk_name = self._get_target_disk(volume)
        logger.debug('start block stream for disk %s' % disk_name)
        self.domain.blockRebase(disk_name, None, 0, 0)

        logger.debug('block stream for disk %s in processing' % disk_name)

        def wait_job(_):
            logger.debug('block stream is waiting for %s blockRebase job completion' % disk_name)
            return not self._wait_for_block_job(disk_name, abort_on_error=True)

        if not linux.wait_callback_success(wait_job, timeout=21600, ignore_exception_in_callback=True):
            raise kvmagent.KvmError('block stream failed')

    def list_blk_sources(self):
        """list domain blocks (aka. domblklist) -- but with sources only"""
        tree = etree.fromstring(self.domain_xml)
        res = []

        for disk in tree.findall("devices/disk"):
            for src in disk.findall("source"):
                src_file = src.get("file")
                if src_file is None:
                    continue

                res.append(src_file)

        return res

    def migrate(self, cmd):
        current_hostname = shell.call('hostname')
        current_hostname = current_hostname.strip(' \t\n\r')
        if cmd.migrateFromDestination:
            hostname = cmd.destHostIp.replace('.', '-')
        else:
            hostname = cmd.srcHostIp.replace('.', '-')

        if current_hostname == 'localhost.localdomain' or current_hostname == 'localhost':
            # set the hostname, otherwise the migration will fail
            shell.call('hostname %s.zstack.org' % hostname)

        destHostIp = cmd.destHostIp
        destUrl = "qemu+tcp://{0}/system".format(destHostIp)
        tcpUri = "tcp://{0}".format(destHostIp)
        flag = (libvirt.VIR_MIGRATE_LIVE |
                libvirt.VIR_MIGRATE_PEER2PEER |
                libvirt.VIR_MIGRATE_UNDEFINE_SOURCE)

        if cmd.autoConverge:
            flag |= libvirt.VIR_MIGRATE_AUTO_CONVERGE

        if cmd.storageMigrationPolicy == 'FullCopy':
            flag |= libvirt.VIR_MIGRATE_NON_SHARED_DISK
        elif cmd.storageMigrationPolicy == 'IncCopy':
            flag |= libvirt.VIR_MIGRATE_NON_SHARED_INC

        # to workaround libvirt bug (c.f. RHBZ#1494454)
        if LIBVIRT_MAJOR_VERSION >= 4:
            if any(s.startswith('/dev/') for s in self.list_blk_sources()):
                flag |= libvirt.VIR_MIGRATE_UNSAFE

        if cmd.useNuma:
            flag |= libvirt.VIR_MIGRATE_PERSIST_DEST

        timeout = 1800 if cmd.timeout is None else cmd.timeout
        def cancel_migration():
            logger.debug('timeout after %d seconds, cancelling migration' % timeout)
            try: self.domain.abortJob()
            except: pass

        t = threading.Timer(timeout, cancel_migration)
        t.start()

        try:
            logger.debug('migrating vm[uuid:{0}] to dest url[{1}]'.format(self.uuid, destUrl))
            self.domain.migrateToURI2(destUrl, tcpUri, None, flag, None, 0)
            t.cancel()
        except libvirt.libvirtError as ex:
            raise kvmagent.KvmError('unable to migrate vm[uuid:%s] to %s, %s' % (self.uuid, destUrl, str(ex)))

        try:
            logger.debug('migrating vm[uuid:{0}] to dest url[{1}]'.format(self.uuid, destUrl))
            timeo = 1800 if cmd.timeout is None else cmd.timeout
            if not linux.wait_callback_success(self.wait_for_state_change, callback_data=None, timeout=timeo):
                try: self.domain.abortJob()
                except: pass
                raise kvmagent.KvmError('timeout after %d seconds' % timeo)
        except kvmagent.KvmError:
            raise
        except:
            logger.debug(linux.get_exception_stacktrace())

        logger.debug('successfully migrated vm[uuid:{0}] to dest url[{1}]'.format(self.uuid, destUrl))

    def _interface_cmd_to_xml(self, cmd):
        interface = Vm._build_interface_xml(cmd.nic)

        def addon():
            if cmd.addons and cmd.addons['NicQos']:
                qos = cmd.addons['NicQos']
                Vm._add_qos_to_interface(interface, qos)

        addon()

        return etree.tostring(interface)

    def _wait_vm_run_until_seconds(self, sec):
        vm_pid = linux.find_process_by_cmdline(['kvm', self.uuid])
        if not vm_pid:
            raise Exception('cannot find pid for vm[uuid:%s]' % self.uuid)

        up_time = linux.get_process_up_time_in_second(vm_pid)

        def wait(_):
            return linux.get_process_up_time_in_second(vm_pid) > sec

        if up_time < sec and not linux.wait_callback_success(wait, timeout=60):
            raise Exception("vm[uuid:%s] seems hang, its process[pid:%s] up-time is not increasing after %s seconds" %
                            (self.uuid, vm_pid, 60))

    def attach_iso(self, cmd):
        iso = cmd.iso

        if iso.deviceId >= len(self.ISO_DEVICE_LETTERS):
            err = 'vm[uuid:%s] exceeds max iso limit, device id[%s], but only 0 ~ %d are allowed' % (self.uuid, iso.deviceId, len(self.ISO_DEVICE_LETTERS) - 1)
            logger.warn(err)
            raise kvmagent.KvmError(err)

        device_letter = self.ISO_DEVICE_LETTERS[iso.deviceId]
        dev = self._get_iso_target_dev(device_letter)
        bus = self._get_controller_type()

        if iso.path.startswith('ceph'):
            ic = IsoCeph()
            ic.iso = iso
            cdrom = ic.to_xmlobject(dev, bus)
        elif iso.path.startswith('fusionstor'):
            ic = IsoFusionstor()
            ic.iso = iso
            cdrom = ic.to_xmlobject(dev, bus)
        else:
            if iso.path.startswith('sharedblock'):
                iso.path = shared_block_to_file(iso.path)

            cdrom = etree.Element('disk', {'type': 'file', 'device': 'cdrom'})
            e(cdrom, 'driver', None, {'name': 'qemu', 'type': 'raw'})
            e(cdrom, 'source', None, {'file': iso.path})
            e(cdrom, 'target', None, {'dev': dev, 'bus': bus})
            e(cdrom, 'readonly', None)

        xml = etree.tostring(cdrom)

        if LIBVIRT_MAJOR_VERSION >= 4:
            addr = find_domain_cdrom_address(self.domain.XMLDesc(0), dev)
            ridx = xml.rindex('<')
            xml = xml[:ridx] + addr.dump() + xml[ridx:]

        logger.debug('attaching ISO to the vm[uuid:%s]:\n%s' % (self.uuid, xml))

        try:
            self.domain.updateDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
        except libvirt.libvirtError as ex:
            err = str(ex)
            logger.warn('unable to attach the iso to the VM[uuid:%s], %s' % (self.uuid, err))

            if "QEMU command 'change': error connecting: Operation not supported" in err:
                raise Exception('cannot hotplug ISO to the VM[uuid:%s]. It is a libvirt bug: %s.'
                        ' you can power-off the vm and attach again.' %
                        (self.uuid, 'https://bugzilla.redhat.com/show_bug.cgi?id=1541702'))

            if 'timed out waiting for disk tray status update' in err:
                raise Exception(
                    'unable to attach the iso to the VM[uuid:%s]. It seems met some internal error,'
                    ' you can reboot the vm and try again' % self.uuid)


        def check(_):
            me = get_vm_by_uuid(self.uuid)
            for disk in me.domain_xmlobject.devices.get_child_node_as_list('disk'):
                if disk.device_ == "cdrom" and xmlobject.has_element(disk, 'source'):
                    if disk.target.dev__ and disk.target.dev_ == dev:
                        return True
            return False

        if not linux.wait_callback_success(check, None, 30, 1):
            raise Exception('cannot attach the iso[%s] for the VM[uuid:%s]. The device is not present after 30s' %
                            (iso.path, cmd.vmUuid))

    def detach_iso(self, cmd):
        cdrom = None
        for disk in self.domain_xmlobject.devices.get_child_node_as_list('disk'):
            if disk.device_ == "cdrom":
                cdrom = disk
                break

        if not cdrom:
            return

        device_letter = self.ISO_DEVICE_LETTERS[cmd.deviceId]
        dev = self._get_iso_target_dev(device_letter)
        bus = self._get_controller_type()

        cdrom = etree.Element('disk', {'type': 'file', 'device': 'cdrom'})
        e(cdrom, 'driver', None, {'name': 'qemu', 'type': 'raw'})
        e(cdrom, 'target', None, {'dev': dev, 'bus': bus})
        e(cdrom, 'readonly', None)

        xml = etree.tostring(cdrom)

        if LIBVIRT_MAJOR_VERSION >= 4:
            addr = find_domain_cdrom_address(self.domain.XMLDesc(0), dev)
            ridx = xml.rindex('<')
            xml = xml[:ridx] + addr.dump() + xml[ridx:]

        logger.debug('detaching ISO from the vm[uuid:%s]:\n%s' % (self.uuid, xml))

        try:
            self.domain.updateDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_DEVICE_MODIFY_FORCE)
        except libvirt.libvirtError as ex:
            err = str(ex)
            logger.warn('unable to detach the iso from the VM[uuid:%s], %s' % (self.uuid, err))
            if 'is locked' in err and 'eject' in err:
                raise Exception(
                    'unable to detach the iso from the VM[uuid:%s]. It seems the ISO is still mounted in the operating system'
                    ', please umount it first' % self.uuid)

        def check(_):
            me = get_vm_by_uuid(self.uuid)
            for disk in me.domain_xmlobject.devices.get_child_node_as_list('disk'):
                if disk.device_ == "cdrom" and xmlobject.has_element(disk, 'source') == False:
                    if disk.target.dev__ and disk.target.dev_ == dev:
                        return True
            return False

        if not linux.wait_callback_success(check, None, 30, 1):
            raise Exception('cannot detach the cdrom from the VM[uuid:%s]. The device is still present after 30s' %
                            self.uuid)

    def _get_controller_type(self):
        is_q35 = 'q35' in self.domain_xmlobject.os.type.machine_
        return ('ide', 'sata', 'scsi')[max(is_q35, IS_AARCH64 * 2)]

    @staticmethod
    def _get_iso_target_dev(device_letter):
        return "sd%s" % device_letter if IS_AARCH64 else 'hd%s' % device_letter

    @staticmethod
    def _get_disk_target_dev_format(bus_type):
        return {'virtio': 'vd%s', 'scsi': 'sd%s', 'sata': 'hd%s', 'ide': 'hd%s'}[bus_type]

    def hotplug_mem(self, memory_size):
        mem_size = (memory_size - self.get_memory()) / 1024
        xml = "<memory model='dimm'><target><size unit='KiB'>%d</size><node>0</node></target></memory>" % mem_size
        logger.debug('hot plug memory: %d KiB' % mem_size)
        try:
            self.domain.attachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        except libvirt.libvirtError as ex:
            err = str(ex)
            logger.warn('unable to hotplug memory in vm[uuid:%s], %s' % (self.uuid, err))
            if "cannot set up guest memory" in err:
                raise kvmagent.KvmError("No enough physical memory for guest")
            elif "would exceed domain's maxMemory config" in err:
                raise kvmagent.KvmError(err + "; please check if you have rebooted the VM to make NUMA take effect")
            else:
                raise kvmagent.KvmError(err)
        return

    def hotplug_cpu(self, cpu_num):

        logger.debug('set cpus: %d cpus' % cpu_num)
        try:
            self.domain.setVcpusFlags(cpu_num, libvirt.VIR_DOMAIN_AFFECT_LIVE | libvirt.VIR_DOMAIN_AFFECT_CONFIG)
        except libvirt.libvirtError as ex:
            err = str(ex)
            logger.warn('unable to set cpus in vm[uuid:%s], %s' % (self.uuid, err))

            if "requested vcpus is greater than max" in err:
                err += "; please check if you have rebooted the VM to make NUMA take effect"

            raise kvmagent.KvmError(err)
        return

    @linux.retry(times=3, sleep_time=5)
    def _attach_nic(self, cmd):
        def check_device(_):
            self.refresh()
            for iface in self.domain_xmlobject.devices.get_child_node_as_list('interface'):
                if iface.mac.address_ == cmd.nic.mac:
                    return shell.run('ip link | grep -w -q %s' % cmd.nic.nicInternalName) == 0

            return False

        try:
            if check_device(None):
                return

            xml = self._interface_cmd_to_xml(cmd)
            logger.debug('attaching nic:\n%s' % xml)
            if self.state == self.VM_STATE_RUNNING or self.state == self.VM_STATE_PAUSED:
                self.domain.attachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            else:
                self.domain.attachDevice(xml)

            if not linux.wait_callback_success(check_device, interval=0.5, timeout=30):
                raise Exception('nic device does not show after 30 seconds')
        except:
            #  check one more time
            if not check_device(None):
                raise

    def attach_nic(self, cmd):
        self._wait_vm_run_until_seconds(10)
        self.timeout_object.wait_until_object_timeout('%s-attach-nic' % self.uuid)
        try:
            self._attach_nic(cmd)
        except libvirt.libvirtError as ex:
            err = str(ex)
            if 'Duplicate ID' in err:
                err = ('unable to attach a L3 network to the vm[uuid:%s], %s. This is a KVM issue, please reboot'
                       ' the vm and try again' % (self.uuid, err))
            elif 'No more available PCI slots' in err:
                err = ('vm[uuid: %s] has no more PCI slots for vm nic[mac:%s]. This is a Libvirt issue, please reboot'
                       ' the VM and try again' % (self.uuid, cmd.nic.mac))
            else:
                err = 'unable to attach a L3 network to the vm[uuid:%s], %s' % (self.uuid, err)
            raise kvmagent.KvmError(err)

        # in 10 seconds, no detach-nic operation can be performed,
        # work around libvirt bug
        self.timeout_object.put('%s-detach-nic' % self.uuid, timeout=10)

    @linux.retry(times=3, sleep_time=5)
    def _detach_nic(self, cmd):
        def check_device(_):
            self.refresh()
            for iface in self.domain_xmlobject.devices.get_child_node_as_list('interface'):
                if iface.mac.address_ == cmd.nic.mac:
                    return False

            return shell.run('ip link show dev %s > /dev/null' % cmd.nic.nicInternalName) != 0

        if check_device(None):
            return

        try:
            xml = self._interface_cmd_to_xml(cmd)
            logger.debug('detaching nic:\n%s' % xml)
            if self.state == self.VM_STATE_RUNNING or self.state == self.VM_STATE_PAUSED:
                self.domain.detachDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            else:
                self.domain.detachDevice(xml)

            if not linux.wait_callback_success(check_device, interval=0.5, timeout=10):
                raise Exception('NIC device is still attached after 10 seconds. Please check virtio driver or stop VM and detach again.')
        except:
            # check one more time
            if not check_device(None):
                logger.warn('failed to detach a nic[mac:%s], dump vm xml:\n%s' % (cmd.nic.mac, self.domain_xml))
                raise

    def detach_nic(self, cmd):
        self._wait_vm_run_until_seconds(10)
        self.timeout_object.wait_until_object_timeout('%s-detach-nic' % self.uuid)
        self._detach_nic(cmd)
        # in 10 seconds, no attach-nic operation can be performed,
        # to work around libvirt bug
        self.timeout_object.put('%s-attach-nic' % self.uuid, timeout=10)

    def update_nic(self, cmd):
        self._wait_vm_run_until_seconds(10)
        self.timeout_object.wait_until_object_timeout('%s-update-nic' % self.uuid)
        self._update_nic(cmd)
        self.timeout_object.put('%s-update-nic' % self.uuid, timeout=10)

    def _update_nic(self, cmd):
        if not cmd.nics:
            return

        def check_device(nic):
            self.refresh()
            for iface in self.domain_xmlobject.devices.get_child_node_as_list('interface'):
                if iface.mac.address_ == nic.mac:
                    return shell.run('ip link | grep -w -q %s' % nic.nicInternalName) == 0

            return False

        def addon(nic_xml_object):
            if cmd.addons and cmd.addons['NicQos'] and cmd.addons['NicQos'][nic.uuid]:
                qos = cmd.addons['NicQos'][nic.uuid]
                Vm._add_qos_to_interface(nic_xml_object, qos)

        for nic in cmd.nics:
            interface = Vm._build_interface_xml(nic)
            addon(interface)
            xml = etree.tostring(interface)
            logger.debug('updating nic:\n%s' % xml)
            if self.state == self.VM_STATE_RUNNING or self.state == self.VM_STATE_PAUSED:
                self.domain.updateDeviceFlags(xml, libvirt.VIR_DOMAIN_AFFECT_LIVE)
            else:
                self.domain.updateDeviceFlags(xml)
            if not linux.wait_callback_success(check_device, nic, interval=0.5, timeout=30):
                raise Exception('nic device does not show after 30 seconds')

    def _check_qemuga_info(self, info):
        if info:
            for command in info["return"]["supported_commands"]:
                if command["name"] == "guest-set-user-password":
                    if command["enabled"]:
                        return True
        return False

    def _wait_until_qemuga_ready(self, timeout, uuid):
        finish_time = time.time() + (timeout / 1000)
        while time.time() < finish_time:
            state = get_all_vm_states().get(uuid)
            if state != Vm.VM_STATE_RUNNING:
                raise kvmagent.KvmError("vm's state is %s, not running" % state)
            ping_json = shell.call('virsh qemu-agent-command %s \'{"execute":"guest-ping"}\'' % self.uuid, False)
            try:
                logger.debug("ping_json: %s" % ping_json)
                if ping_json.find("{\"return\":{}}") != -1:
                    return True
            except Exception as err:
                logger.warn(err.message)
            time.sleep(2)
        raise kvmagent.KvmError("qemu-agent service is not ready in vm...")

    def _escape_char_password(self, password):
        escape_str = "\*\#\(\)\<\>\|\"\'\/\\\$\`\&\{\}"
        des = ""
        for c in list(password):
            if c in escape_str:
                des += "\\"
            des += c
        return des

    def change_vm_password(self, cmd):
        uuid = self.uuid
        # check the vm state first, then choose the method in different way
        state = get_all_vm_states().get(uuid)
        timeout = 60000
        if state == Vm.VM_STATE_RUNNING:
            # before set-user-password, we must check if os ready in the guest
            self._wait_until_qemuga_ready(timeout, uuid)
            try:
                escape_password = self._escape_char_password(cmd.accountPerference.accountPassword)
                shell.call('virsh set-user-password %s %s %s' % (self.uuid,
                                                                 cmd.accountPerference.userAccount,
                                                                 escape_password))
            except Exception as e:
                logger.warn(e.message)
                if e.message.find("child process has failed to set user password") > 0:
                    logger.warn('user [%s] not exist!' % cmd.accountPerference.userAccount)
                    raise kvmagent.KvmError('user [%s] not exist!' % cmd.accountPerference.userAccount)
                else:
                    raise e
        else:
            raise kvmagent.KvmError("vm is not running, cannot connect to qemu-ga")

    def merge_snapshot(self, cmd):
        target_disk, disk_name = self._get_target_disk(cmd.volume)

        @linux.retry(times=3, sleep_time=3)
        def do_pull(base, top):
            logger.debug('start block rebase [active: %s, new backing: %s]' % (top, base))

            # Double check (c.f. issue #1323)
            def wait_previous_job(_):
                logger.debug('merge snapshot is checking previous block job')
                return not self._wait_for_block_job(disk_name, abort_on_error=True)

            if not linux.wait_callback_success(wait_previous_job, timeout=21600, ignore_exception_in_callback=True):
                raise kvmagent.KvmError('merge snapshot failed - pending previous block job')

            self.domain.blockRebase(disk_name, base, 0)

            def wait_job(_):
                logger.debug('merging snapshot chain is waiting for blockRebase job completion')
                return not self._wait_for_block_job(disk_name, abort_on_error=True)

            if not linux.wait_callback_success(wait_job, timeout=21600):
                raise kvmagent.KvmError('live merging snapshot chain failed, timeout after 6 hours')

            # Double check (c.f. issue #757)
            if self._get_back_file(top) != base:
                raise kvmagent.KvmError('[bug] live merge snapshot failed')

            logger.debug('end block rebase [active: %s, new backing: %s]' % (top, base))

        if cmd.fullRebase:
            do_pull(None, cmd.destPath)
        else:
            do_pull(cmd.srcPath, cmd.destPath)

    @staticmethod
    def from_virt_domain(domain):
        vm = Vm()
        vm.domain = domain
        (state, _, _, _, _) = domain.info()
        vm.state = Vm.power_state[state]
        vm.domain_xml = domain.XMLDesc(0)
        vm.domain_xmlobject = xmlobject.loads(vm.domain_xml)
        vm.uuid = vm.domain_xmlobject.name.text_

        return vm

    @staticmethod
    def from_StartVmCmd(cmd):
        use_numa = cmd.useNuma
        machine_type = cmd.machineType if cmd.machineType else 'pc'
        default_bus_type = ('ide', 'sata', 'scsi')[max(machine_type == 'q35', IS_AARCH64 * 2)]
        elements = {}

        def make_root():
            root = etree.Element('domain')
            root.set('type', 'kvm')
            # self._root.set('type', 'qemu')
            root.set('xmlns:qemu', 'http://libvirt.org/schemas/domain/qemu/1.0')
            elements['root'] = root

        def make_cpu():
            if use_numa and not IS_AARCH64:
                root = elements['root']
                e(root, 'vcpu', '128', {'placement': 'static', 'current': str(cmd.cpuNum)})
                # e(root,'vcpu',str(cmd.cpuNum),{'placement':'static'})
                tune = e(root, 'cputune')
                e(tune, 'shares', str(cmd.cpuSpeed * cmd.cpuNum))
                # enable nested virtualization
                if cmd.nestedVirtualization == 'host-model':
                    cpu = e(root, 'cpu', attrib={'mode': 'host-model'})
                    e(cpu, 'model', attrib={'fallback': 'allow'})
                elif cmd.nestedVirtualization == 'host-passthrough':
                    cpu = e(root, 'cpu', attrib={'mode': 'host-passthrough'})
                    e(cpu, 'model', attrib={'fallback': 'allow'})
                elif cmd.nestedVirtualization == 'custom':
                    cpu = e(root, 'cpu', attrib={'mode': 'custom', 'match': 'minimum'})
                    e(cpu, 'model', cmd.vmCpuModel, attrib={'fallback': 'allow'})
                elif IS_AARCH64:
                    cpu = e(root, 'cpu', attrib={'mode': 'host-passthrough'})
                    e(cpu, 'model', attrib={'fallback': 'allow'})
                else:
                    cpu = e(root, 'cpu')
                    # e(cpu, 'topology', attrib={'sockets': str(cmd.socketNum), 'cores': str(cmd.cpuOnSocket), 'threads': '1'})
                mem = cmd.memory / 1024
                e(cpu, 'topology', attrib={'sockets': str(32), 'cores': str(4), 'threads': '1'})
                numa = e(cpu, 'numa')
                e(numa, 'cell', attrib={'id': '0', 'cpus': '0-127', 'memory': str(mem), 'unit': 'KiB'})
            else:
                root = elements['root']
                # e(root, 'vcpu', '128', {'placement': 'static', 'current': str(cmd.cpuNum)})
                e(root, 'vcpu', str(cmd.cpuNum), {'placement': 'static'})
                tune = e(root, 'cputune')
                e(tune, 'shares', str(cmd.cpuSpeed * cmd.cpuNum))
                # enable nested virtualization
                if cmd.nestedVirtualization == 'host-model':
                    cpu = e(root, 'cpu', attrib={'mode': 'host-model'})
                    e(cpu, 'model', attrib={'fallback': 'allow'})
                elif cmd.nestedVirtualization == 'host-passthrough':
                    cpu = e(root, 'cpu', attrib={'mode': 'host-passthrough'})
                    e(cpu, 'model', attrib={'fallback': 'allow'})
                elif cmd.nestedVirtualization == 'custom':
                    cpu = e(root, 'cpu', attrib={'mode': 'custom'})
                    e(cpu, 'model', cmd.vmCpuModel, attrib={'fallback': 'allow'})
                elif IS_AARCH64:
                    cpu = e(root, 'cpu', attrib={'mode': 'host-passthrough'})
                    e(cpu, 'model', attrib={'fallback': 'allow'})
                else:
                    cpu = e(root, 'cpu')
                e(cpu, 'topology', attrib={'sockets': str(cmd.socketNum), 'cores': str(cmd.cpuOnSocket), 'threads': '1'})

            if cmd.addons.cpuPinning:
                for rule in cmd.addons.cpuPinning:
                    e(tune, 'vcpupin', attrib={'vcpu': str(rule.vCpu), 'cpuset': rule.pCpuSet})

        def make_memory():
            root = elements['root']
            mem = cmd.memory / 1024
            if use_numa and not IS_AARCH64:
                e(root, 'maxMemory', str(68719476736), {'slots': str(16), 'unit': 'KiB'})
                # e(root,'memory',str(mem),{'unit':'k'})
                e(root, 'currentMemory', str(mem), {'unit': 'k'})
            else:
                e(root, 'memory', str(mem), {'unit': 'k'})
                e(root, 'currentMemory', str(mem), {'unit': 'k'})

        def make_os():
            root = elements['root']
            os = e(root, 'os')
            if IS_AARCH64:
                e(os, 'type', 'hvm', attrib={'arch': 'aarch64'})
                e(os, 'loader', '/usr/share/edk2.git/aarch64/QEMU_EFI-pflash.raw', attrib={'readonly': 'yes', 'type': 'pflash'})
            else:
                e(os, 'type', 'hvm', attrib={'machine': machine_type})
                # if boot mode is UEFI
                if cmd.bootMode == "UEFI":
                    e(os, 'loader', '/usr/share/edk2.git/ovmf-x64/OVMF_CODE-pure-efi.fd', attrib={'readonly': 'yes', 'type': 'pflash'})
                    e(os, 'nvram', '/var/lib/libvirt/qemu/nvram/%s.fd' % cmd.vmInstanceUuid, attrib={'template': '/usr/share/edk2.git/ovmf-x64/OVMF_VARS-pure-efi.fd'})
            # if not booting from cdrom, don't add any boot element in os section
            if cmd.bootDev[0] == "cdrom":
                for boot_dev in cmd.bootDev:
                    e(os, 'boot', None, {'dev': boot_dev})

            if cmd.useBootMenu:
                e(os, 'bootmenu', attrib={'enable': 'yes'})

            if cmd.systemSerialNumber:
                e(os, 'smbios', attrib={'mode': 'sysinfo'})

        def make_sysinfo():
            if not cmd.systemSerialNumber:
                return

            root = elements['root']
            sysinfo = e(root, 'sysinfo', attrib={'type': 'smbios'})
            system = e(sysinfo, 'system')
            e(system, 'entry', cmd.systemSerialNumber, attrib={'name': 'serial'})

        def make_features():
            root = elements['root']
            features = e(root, 'features')
            for f in ['acpi', 'apic', 'pae']:
                e(features, f)
            if cmd.kvmHiddenState is True:
                kvm = e(features, "kvm")
                e(kvm, 'hidden', None, {'state': 'on'})
            if cmd.vmPortOff is True:
                e(features, 'vmport', attrib={'state': 'off'})
            if cmd.emulateHyperV is True:
                hyperv = e(features, "hyperv")
                e(hyperv, 'relaxed', attrib={'state': 'on'})
                e(hyperv, 'vapic', attrib={'state': 'on'})
                e(hyperv, 'spinlocks', attrib={'state': 'on', 'retries': '4096'})
                e(hyperv, 'vendor_id', attrib={'state': 'on', 'value': 'ZStack_Org'})

        def make_qemu_commandline():
            if not os.path.exists(QMP_SOCKET_PATH):
                os.mkdir(QMP_SOCKET_PATH)

            root = elements['root']
            qcmd = e(root, 'qemu:commandline')
            e(qcmd, "qemu:arg", attrib={"value": "-qmp"})
            e(qcmd, "qemu:arg", attrib={"value": "unix:%s/%s.sock,server,nowait" %
                                        (QMP_SOCKET_PATH, cmd.vmInstanceUuid)})

        def make_devices():
            root = elements['root']
            devices = e(root, 'devices')
            if cmd.addons and cmd.addons['qemuPath']:
                e(devices, 'emulator', cmd.addons['qemuPath'])
            else:
                e(devices, 'emulator', kvmagent.get_qemu_path())
            # no default usb controller and tablet device for appliance vm
            if cmd.isApplianceVm:
                e(devices, 'controller', None, {'type': 'usb', 'model': 'none'})
                elements['devices'] = devices
                return

            tablet = e(devices, 'input', None, {'type': 'tablet', 'bus': 'usb'})
            e(tablet, 'address', None, {'type':'usb', 'bus':'0', 'port':'1'})
            if IS_AARCH64:
                keyboard = e(devices, 'input', None, {'type': 'keyboard', 'bus': 'usb'})
            elements['devices'] = devices

        def make_cdrom():
            devices = elements['devices']

            max_cdrom_num = len(Vm.ISO_DEVICE_LETTERS)
            empty_cdrom_configs = None

            if IS_AARCH64:
                # SCSI controller only supports 1 bus
                empty_cdrom_configs = [
                    EmptyCdromConfig('sd%s' % Vm.ISO_DEVICE_LETTERS[0], '0', Vm.get_iso_device_unit(0)),
                    EmptyCdromConfig('sd%s' % Vm.ISO_DEVICE_LETTERS[1], '0', Vm.get_iso_device_unit(1)),
                    EmptyCdromConfig('sd%s' % Vm.ISO_DEVICE_LETTERS[2], '0', Vm.get_iso_device_unit(2))
                ]
            else:
                if cmd.fromForeignHypervisor:
                    cdroms = cmd.addons['FIXED_CDROMS']

                    if cdroms is None:
                        empty_cdrom_configs = [
                            EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[0], '0', '1')
                        ]
                    else:
                        cdrom_device_id_list = cdroms.split(',')

                        empty_cdrom_configs = []
                        for i in xrange(len(cdrom_device_id_list)):
                            empty_cdrom_configs.append(
                                EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[i], str(i / 2), str(i % 2)))
                elif machine_type == 'q35':
                    # bus 0 unit 0 already use by root volume if it is on sata
                    empty_cdrom_configs = [
                        EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[0], '0', '1'),
                        EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[1], '0', '2'),
                        EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[2], '0', '3'),
                    ]
                else:  # machine_type=pc
                    # bus 0 unit 0 already use by root volume if it is on ide
                    empty_cdrom_configs = [
                        EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[0], '0', '1'),
                        EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[1], '1', '0'),
                        EmptyCdromConfig('hd%s' % Vm.ISO_DEVICE_LETTERS[2], '1', '1')
                    ]

            if len(empty_cdrom_configs) != max_cdrom_num:
                logger.error('ISO_DEVICE_LETTERS or EMPTY_CDROM_CONFIGS config error')

            def make_empty_cdrom(target_dev, bus, unit):
                cdrom = e(devices, 'disk', None, {'type': 'file', 'device': 'cdrom'})
                e(cdrom, 'driver', None, {'name': 'qemu', 'type': 'raw'})
                e(cdrom, 'target', None, {'dev': target_dev, 'bus': default_bus_type})
                e(cdrom, 'address', None, {'type': 'drive', 'bus': bus, 'unit': unit})
                e(cdrom, 'readonly', None)
                return cdrom

            """
            if not cmd.bootIso:
                for config in empty_cdrom_configs:
                    makeEmptyCdrom(config.targetDev, config.bus, config.unit)
                return
            """
            if not cmd.cdRoms:
                return

            for iso in cmd.cdRoms:
                cdrom_config = empty_cdrom_configs[iso.deviceId]

                if iso.isEmpty:
                    make_empty_cdrom(cdrom_config.targetDev, cdrom_config.bus, cdrom_config.unit)
                    continue

                if iso.path.startswith('ceph'):
                    ic = IsoCeph()
                    ic.iso = iso
                    devices.append(ic.to_xmlobject(cdrom_config.targetDev, default_bus_type, cdrom_config.bus, cdrom_config.unit))
                elif iso.path.startswith('fusionstor'):
                    ic = IsoFusionstor()
                    ic.iso = iso
                    devices.append(ic.to_xmlobject(cdrom_config.targetDev, default_bus_type, cdrom_config.bus, cdrom_config.unit))
                else:
                    cdrom = make_empty_cdrom(cdrom_config.targetDev, cdrom_config.bus , cdrom_config.unit)
                    e(cdrom, 'source', None, {'file': iso.path})

        def make_volumes():
            devices = elements['devices']
            volumes = [cmd.rootVolume]
            volumes.extend(cmd.dataVolumes)

            def filebased_volume(_dev_letter, _v):
                disk = etree.Element('disk', {'type': 'file', 'device': 'disk', 'snapshot': 'external'})
                e(disk, 'driver', None, {'name': 'qemu', 'type': linux.get_img_fmt(_v.installPath), 'cache': _v.cacheMode})
                e(disk, 'source', None, {'file': _v.installPath})

                if _v.shareable:
                    e(disk, 'shareable')

                if _v.useVirtioSCSI:
                    e(disk, 'target', None, {'dev': 'sd%s' % _dev_letter, 'bus': 'scsi'})
                    e(disk, 'wwn', _v.wwn)
                    e(disk, 'address', None, {'type': 'drive', 'controller': '0', 'unit': Vm.get_device_unit(_v.deviceId)})
                    return disk

                if _v.useVirtio:
                    e(disk, 'target', None, {'dev': 'vd%s' % _dev_letter, 'bus': 'virtio'})
                else:
                    dev_format = Vm._get_disk_target_dev_format(default_bus_type)
                    e(disk, 'target', None, {'dev': dev_format % _dev_letter, 'bus': default_bus_type})
                return disk

            def iscsibased_volume(_dev_letter, _v):
                def blk_iscsi():
                    bi = BlkIscsi()
                    portal, bi.target, bi.lun = _v.installPath.lstrip('iscsi://').split('/')
                    bi.server_hostname, bi.server_port = portal.split(':')
                    bi.device_letter = _dev_letter
                    bi.volume_uuid = _v.volumeUuid
                    bi.chap_username = _v.chapUsername
                    bi.chap_password = _v.chapPassword

                    return bi.to_xmlobject()

                def virtio_iscsi():
                    vi = VirtioIscsi()
                    portal, vi.target, vi.lun = _v.installPath.lstrip('iscsi://').split('/')
                    vi.server_hostname, vi.server_port = portal.split(':')
                    vi.device_letter = _dev_letter
                    vi.volume_uuid = _v.volumeUuid
                    vi.chap_username = _v.chapUsername
                    vi.chap_password = _v.chapPassword

                    return vi.to_xmlobject()

                if _v.useVirtio:
                    return virtio_iscsi()
                else:
                    return blk_iscsi()

            def ceph_volume(_dev_letter, _v):
                def ceph_virtio():
                    vc = VirtioCeph()
                    vc.volume = _v
                    vc.dev_letter = _dev_letter
                    return vc.to_xmlobject()

                def ceph_blk():
                    ic = BlkCeph()
                    ic.volume = _v
                    ic.dev_letter = _dev_letter
                    ic.bus_type = default_bus_type
                    return ic.to_xmlobject()

                def ceph_virtio_scsi():
                    vsc = VirtioSCSICeph()
                    vsc.volume = _v
                    vsc.dev_letter = _dev_letter
                    return vsc.to_xmlobject()

                if _v.useVirtioSCSI:
                    disk = ceph_virtio_scsi()
                    if _v.shareable:
                        e(disk, 'shareable')
                    return disk

                if _v.useVirtio:
                    return ceph_virtio()
                else:
                    return ceph_blk()

            def fusionstor_volume(_dev_letter, _v):
                def fusionstor_virtio():
                    vc = VirtioFusionstor()
                    vc.volume = _v
                    vc.dev_letter = _dev_letter
                    return vc.to_xmlobject()

                def fusionstor_blk():
                    ic = BlkFusionstor()
                    ic.volume = _v
                    ic.dev_letter = _dev_letter
                    ic.bus_type = default_bus_type
                    return ic.to_xmlobject()

                def fusionstor_virtio_scsi():
                    vsc = VirtioSCSIFusionstor()
                    vsc.volume = _v
                    vsc.dev_letter = _dev_letter
                    return vsc.to_xmlobject()

                if _v.useVirtioSCSI:
                    disk = fusionstor_virtio_scsi()
                    if _v.shareable:
                        e(disk, 'shareable')
                    return disk

                if _v.useVirtio:
                    return fusionstor_virtio()
                else:
                    return fusionstor_blk()

            def block_volume(_dev_letter, _v):
                disk = etree.Element('disk', {'type': 'block', 'device': 'disk', 'snapshot': 'external'})
                e(disk, 'driver', None,
                  {'name': 'qemu', 'type': 'raw', 'cache': 'none', 'io': 'native'})
                e(disk, 'source', None, {'dev': _v.installPath})

                if _v.useVirtioSCSI:
                    e(disk, 'target', None, {'dev': 'sd%s' % _dev_letter, 'bus': 'scsi'})
                    e(disk, 'wwn', _v.wwn)
                else:
                    e(disk, 'target', None, {'dev': 'vd%s' % _dev_letter, 'bus': 'virtio'})

                return disk

            def volume_qos(volume_xml_obj):
                if not cmd.addons:
                    return

                vol_qos = cmd.addons['VolumeQos']
                if not vol_qos:
                    return

                qos = vol_qos[v.volumeUuid]
                if not qos:
                    return

                if not qos.totalBandwidth and not qos.totalIops:
                    return

                iotune = e(volume_xml_obj, 'iotune')
                if qos.totalBandwidth:
                    e(iotune, 'total_bytes_sec', str(qos.totalBandwidth))
                if qos.totalIops:
                    # e(iotune, 'total_iops_sec', str(qos.totalIops))
                    e(iotune, 'read_iops_sec', str(qos.totalIops))
                    e(iotune, 'write_iops_sec', str(qos.totalIops))
                    # e(iotune, 'read_iops_sec_max', str(qos.totalIops))
                    # e(iotune, 'write_iops_sec_max', str(qos.totalIops))
                    # e(iotune, 'total_iops_sec_max', str(qos.totalIops))

            def volume_native_aio(volume_xml_obj):
                if not cmd.addons:
                    return

                vol_aio = cmd.addons['NativeAio']
                if not vol_aio:
                    return

                drivers = volume_xml_obj.getiterator("driver")
                if drivers is None or len(drivers) == 0:
                    return

                drivers[0].set("io", "native")

            volumes.sort(key=lambda d: d.deviceId)
            scsi_device_ids = [v.deviceId for v in volumes if v.useVirtioSCSI]
            for v in volumes:
                if v.deviceId >= len(Vm.DEVICE_LETTERS):
                    err = "exceeds max disk limit, device id[%s], but only 0 ~ %d are allowed" % (v.deviceId, len(Vm.DEVICE_LETTERS) - 1)
                    logger.warn(err)
                    raise kvmagent.KvmError(err)

                dev_letter = Vm.DEVICE_LETTERS[v.deviceId]
                if v.useVirtioSCSI:
                    dev_letter = Vm.DEVICE_LETTERS[scsi_device_ids.pop()]

                if v.deviceType == 'file':
                    vol = filebased_volume(dev_letter, v)
                elif v.deviceType == 'iscsi':
                    vol = iscsibased_volume(dev_letter, v)
                elif v.deviceType == 'ceph':
                    vol = ceph_volume(dev_letter, v)
                elif v.deviceType == 'fusionstor':
                    vol = fusionstor_volume(dev_letter, v)
                elif v.deviceType == 'block':
                    vol = block_volume(dev_letter, v)
                else:
                    raise Exception('unknown volume deviceType: %s' % v.deviceType)

                assert vol is not None, 'vol cannot be None'
                # set boot order for root volume when boot from hd
                if v.deviceId == 0 and cmd.bootDev[0] == 'hd' and cmd.useBootMenu:
                    e(vol, 'boot', None, {'order': '1'})
                Vm.set_volume_qos(cmd.addons, v.volumeUuid, vol)
                volume_native_aio(vol)
                devices.append(vol)

        def make_nics():
            if not cmd.nics:
                return

            def addon(nic_xml_object):
                if cmd.addons and cmd.addons['NicQos'] and cmd.addons['NicQos'][nic.uuid]:
                    qos = cmd.addons['NicQos'][nic.uuid]
                    Vm._add_qos_to_interface(nic_xml_object, qos)

            devices = elements['devices']
            for nic in cmd.nics:
                interface = Vm._build_interface_xml(nic, devices)
                addon(interface)

        def make_meta():
            root = elements['root']

            e(root, 'name', cmd.vmInstanceUuid)
            e(root, 'uuid', uuidhelper.to_full_uuid(cmd.vmInstanceUuid))
            e(root, 'description', cmd.vmName)
            e(root, 'on_poweroff', 'destroy')
            e(root, 'on_crash', 'restart')
            e(root, 'on_reboot', 'restart')
            meta = e(root, 'metadata')
            zs = e(meta, 'zstack', usenamesapce=True)
            e(zs, 'internalId', str(cmd.vmInternalId))
            e(zs, 'hostManagementIp', str(cmd.hostManagementIp))
            clock = e(root, 'clock', None, {'offset': cmd.clock})
            if cmd.clock == 'localtime':
                e(clock, 'timer', None, {'name': 'rtc', 'tickpolicy': 'catchup'})
                e(clock, 'timer', None, {'name': 'pit', 'tickpolicy': 'delay'})
                e(clock, 'timer', None, {'name': 'hpet', 'present': 'no'})
                e(clock, 'timer', None, {'name': 'hypervclock', 'present': 'yes'})

        def make_vnc():
            devices = elements['devices']
            if cmd.consolePassword == None:
                vnc = e(devices, 'graphics', None, {'type': 'vnc', 'port': '5900', 'autoport': 'yes'})
            else:
                vnc = e(devices, 'graphics', None,
                        {'type': 'vnc', 'port': '5900', 'autoport': 'yes', 'passwd': str(cmd.consolePassword)})
            e(vnc, "listen", None, {'type': 'address', 'address': '0.0.0.0'})

        def make_spice():
            devices = elements['devices']
            spice = e(devices, 'graphics', None, {'type': 'spice', 'port': '5900', 'autoport': 'yes'})
            e(spice, "listen", None, {'type': 'address', 'address': '0.0.0.0'})
            e(spice, "image", None, {'compression': 'auto_glz'})
            e(spice, "jpeg", None, {'compression': 'always'})
            e(spice, "zlib", None, {'compression': 'never'})
            e(spice, "playback", None, {'compression': 'off'})
            e(spice, "streaming", None, {'mode': cmd.spiceStreamingMode})
            e(spice, "mouse", None, {'mode': 'client'})
            e(spice, "filetransfer", None, {'enable': 'no'})
            e(spice, "clipboard", None, {'copypaste': 'no'})

        def make_usb_redirect():
            devices = elements['devices']
            e(devices, 'controller', None, {'type': 'usb', 'index': '0'})

            # if aarch64, then only create default usb controller
            if IS_AARCH64:
                return

            # make sure there are three usb controllers, each for USB 1.1/2.0/3.0
            e(devices, 'controller', None, {'type': 'usb', 'index': '1', 'model': 'ehci'})
            e(devices, 'controller', None, {'type': 'usb', 'index': '2', 'model': 'nec-xhci'})

            # USB2.0 Controller for redirect
            e(devices, 'controller', None, {'type': 'usb', 'index': '3', 'model': 'ehci'})
            e(devices, 'controller', None, {'type': 'usb', 'index': '4', 'model': 'nec-xhci'})
            chan = e(devices, 'channel', None, {'type': 'spicevmc'})
            e(chan, 'target', None, {'type': 'virtio', 'name': 'com.redhat.spice.0'})
            e(chan, 'address', None, {'type': 'virtio-serial'})

            redirdev1 = e(devices, 'redirdev', None, {'type': 'spicevmc', 'bus': 'usb'})
            e(redirdev1, 'address', None, {'type': 'usb', 'bus': '3', 'port': '1'})
            redirdev2 = e(devices, 'redirdev', None, {'type': 'spicevmc', 'bus': 'usb'})
            e(redirdev2, 'address', None, {'type': 'usb', 'bus': '3', 'port': '2'})
            redirdev3 = e(devices, 'redirdev', None, {'type': 'spicevmc', 'bus': 'usb'})
            e(redirdev3, 'address', None, {'type': 'usb', 'bus': '4', 'port': '1'})
            redirdev4 = e(devices, 'redirdev', None, {'type': 'spicevmc', 'bus': 'usb'})
            e(redirdev4, 'address', None, {'type': 'usb', 'bus': '4', 'port': '2'})

        def make_video():
            devices = elements['devices']
            if IS_AARCH64:
                video = e(devices, 'video')
                e(video, 'model', None, {'type': 'virtio'})
            elif cmd.videoType != "qxl":
                video = e(devices, 'video')
                e(video, 'model', None, {'type': str(cmd.videoType)})
            else:
                for monitor in range(cmd.VDIMonitorNumber):
                    video = e(devices, 'video')
                    e(video, 'model', None, {'type': str(cmd.videoType)})


        def make_audio_microphone():
            if cmd.consoleMode == 'spice':
                devices = elements['devices']
                e(devices, 'sound',None,{'model':'ich6'})
            else:
                return

        def make_graphic_console():
            if cmd.consoleMode == 'spice':
                make_spice()
            else:
                make_vnc()

        def make_addons():
            if not cmd.addons:
                return

            devices = elements['devices']
            channel = cmd.addons['channel']
            if channel:
                basedir = os.path.dirname(channel.socketPath)
                linux.mkdir(basedir, 0777)
                chan = e(devices, 'channel', None, {'type': 'unix'})
                e(chan, 'source', None, {'mode': 'bind', 'path': channel.socketPath})
                e(chan, 'target', None, {'type': 'virtio', 'name': channel.targetName})

            cephSecretKey = cmd.addons['ceph_secret_key']
            cephSecretUuid = cmd.addons['ceph_secret_uuid']
            if cephSecretKey and cephSecretUuid:
                VmPlugin._create_ceph_secret_key(cephSecretKey, cephSecretUuid)

            pciDevices = cmd.addons['pciDevice']
            if pciDevices:
                make_pci_device(pciDevices)

            storageDevices = cmd.addons['storageDevice']
            if storageDevices:
                make_storage_device(storageDevices)

            usbDevices = cmd.addons['usbDevice']
            if usbDevices:
                make_usb_device(usbDevices)

        def make_storage_device(storageDevices):
            lvm.unpriv_sgio()
            devices = elements['devices']
            for volume in storageDevices:
                if match_storage_device(volume.installPath):
                    disk = e(devices, 'disk', None, attrib={'type': 'block', 'device': 'lun', 'sgio': 'unfiltered'})
                    e(disk, 'driver', None, {'name': 'qemu', 'type': 'raw'})
                    e(disk, 'source', None, {'dev': volume.installPath})
                    e(disk, 'target', None, {'dev': 'sd%s' % Vm.DEVICE_LETTERS[volume.deviceId], 'bus': 'scsi'})

        def make_pci_device(addresses):
            devices = elements['devices']
            for addr in addresses:
                if match_pci_device(addr):
                    hostdev = e(devices, "hostdev", None, {'mode': 'subsystem', 'type': 'pci', 'managed': 'yes'})
                    e(hostdev, "driver", None, {'name': 'vfio'})
                    source = e(hostdev, "source")
                    e(source, "address", None, {
                        "domain": hex(0) if len(addr.split(":")) == 2 else hex(int(addr.split(":")[0], 16)),
                        "bus": hex(int(addr.split(":")[-2], 16)),
                        "slot": hex(int(addr.split(":")[-1].split(".")[0], 16)),
                        "function": hex(int(addr.split(":")[-1].split(".")[1], 16))
                    })
                else:
                    raise kvmagent.KvmError(
                       'can not find pci device for address %s' % addr)

        def make_usb_device(usbDevices):
            next_uhci_port = 2
            next_ehci_port = 1
            next_xhci_port = 1
            devices = elements['devices']
            for usb in usbDevices:
                if match_usb_device(usb):
                    hostdev = e(devices, "hostdev", None, {'mode': 'subsystem', 'type': 'usb', 'managed': 'yes'})
                    source = e(hostdev, "source")
                    e(source, "address", None, {
                        "bus": str(int(usb.split(":")[0])),
                        "device": str(int(usb.split(":")[1]))
                    })
                    e(source, "vendor", None, {
                        "id": hex(int(usb.split(":")[2], 16))
                    })
                    e(source, "product", None, {
                        "id": hex(int(usb.split(":")[3], 16))
                    })

                    # get controller index from usbVersion
                    # eg. 1.1 -> 0
                    # eg. 2.0.0 -> 1
                    # eg. 3 -> 2
                    bus = int(usb.split(":")[4][0]) - 1
                    if bus == 0:
                        address = e(hostdev, "address", None, {'type': 'usb', 'bus': str(bus), 'port': str(next_uhci_port)})
                        next_uhci_port += 1
                    elif bus == 1:
                        address = e(hostdev, "address", None, {'type': 'usb', 'bus': str(bus), 'port': str(next_ehci_port)})
                        next_ehci_port += 1
                    elif bus == 2:
                        address = e(hostdev, "address", None, {'type': 'usb', 'bus': str(bus), 'port': str(next_xhci_port)})
                        next_xhci_port += 1
                    else:
                        raise kvmagent.KvmError('unknown usb controller %s', bus)
                else:
                    raise kvmagent.KvmError('cannot find usb device %s', usb)

        #TODO(weiw) validate here
        def match_storage_device(install_path):
            return True

        # TODO(WeiW) Validate here
        def match_pci_device(addr):
            return True

        def match_usb_device(addr):
            if len(addr.split(':')) == 5:
                return True
            else:
                return False

        def make_balloon_memory():
            devices = elements['devices']
            b = e(devices, 'memballoon', None, {'model': 'virtio'})
            e(b, 'stats', None, {'period': '10'})

        def make_console():
            devices = elements['devices']
            serial = e(devices, 'serial', None, {'type': 'pty'})
            e(serial, 'target', None, {'port': '0'})
            console = e(devices, 'console', None, {'type': 'pty'})
            e(console, 'target', None, {'type': 'serial', 'port': '0'})

        def make_sec_label():
            root = elements['root']
            e(root, 'seclabel', None, {'type': 'none'})

        def make_controllers():
            devices = elements['devices']
            e(devices, 'controller', None, {'type': 'scsi', 'model': 'virtio-scsi'})

            if machine_type == "q35":
                controller = e(devices, 'controller', None, {'type': 'sata', 'index': '0'})
                e(controller, 'alias', None, {'name': 'sata'})
                e(controller, 'address', None, {'type': 'pci', 'domain': '0', 'bus': '0', 'slot': '0x1f', 'function': '2'})

                pci_idx_generator = range(cmd.pciePortNums + 3).__iter__()
                e(devices, 'controller', None, {'type': 'pci', 'model': 'pcie-root', 'index': str(pci_idx_generator.next())})
                e(devices, 'controller', None, {'type': 'pci', 'model': 'dmi-to-pci-bridge', 'index': str(pci_idx_generator.next())})
                e(devices, 'controller', None, {'type': 'pci', 'model': 'pci-bridge', 'index': str(pci_idx_generator.next())})
                for i in pci_idx_generator:
                    e(devices, 'controller', None, {'type': 'pci', 'model': 'pcie-root-port', 'index': str(i)})


        make_root()
        make_meta()
        make_cpu()
        make_memory()
        make_os()
        make_sysinfo()
        make_features()
        make_devices()
        make_video()
        make_audio_microphone()
        make_nics()
        make_volumes()
        make_graphic_console()
        make_addons()
        make_balloon_memory()
        make_console()
        make_sec_label()
        make_controllers()
        # appliance vm doesn't need any cdrom or usb controller
        if not cmd.isApplianceVm:
            make_cdrom()
            make_usb_redirect()

        if cmd.additionalQmp:
            make_qemu_commandline()

        root = elements['root']
        xml = etree.tostring(root)

        vm = Vm()
        vm.uuid = cmd.vmInstanceUuid
        vm.domain_xml = xml
        vm.domain_xmlobject = xmlobject.loads(xml)
        return vm

    @staticmethod
    def _build_interface_xml(nic, devices=None):
        if devices:
            interface = e(devices, 'interface', None, {'type': 'bridge'})
        else:
            interface = etree.Element('interface', attrib={'type': 'bridge'})

        e(interface, 'mac', None, attrib={'address': nic.mac})
        e(interface, 'source', None, attrib={'bridge': nic.bridgeName})
        e(interface, 'target', None, attrib={'dev': nic.nicInternalName})
        e(interface, 'alias', None, {'name': 'net%s' % nic.nicInternalName.split('.')[1]})
        if nic.ips:
            ip4Addr = None
            ip6Addrs = []
            for addr in nic.ips:
                version = netaddr.IPAddress(addr).version
                if version == 4:
                    ip4Addr = addr
                else:
                    ip6Addrs.append(addr)
            # ipv4 nic
            if ip4Addr is not None and len(ip6Addrs) == 0:
                filterref = e(interface, 'filterref', None, {'filter': 'clean-traffic'})
                e(filterref, 'parameter', None, {'name': 'IP', 'value': ip4Addr})
            elif ip4Addr is None and len(ip6Addrs) > 0:  # ipv6 nic
                filterref = e(interface, 'filterref', None, {'filter': 'zstack-clean-traffic-ipv6'})
                for addr6 in ip6Addrs:
                    e(filterref, 'parameter', None, {'name': 'GLOBAL_IP', 'value': addr6})
                e(filterref, 'parameter', None, {'name': 'LINK_LOCAL_IP', 'value': ip.get_link_local_address(nic.mac)})
            else:  # dual stack nic
                filterref = e(interface, 'filterref', None, {'filter': 'zstack-clean-traffic-ip46'})
                e(filterref, 'parameter', None, {'name': 'IP', 'value': ip4Addr})
                for addr6 in ip6Addrs:
                    e(filterref, 'parameter', None, {'name': 'GLOBAL_IP', 'value': addr6})
                e(filterref, 'parameter', None, {'name': 'LINK_LOCAL_IP', 'value': ip.get_link_local_address(nic.mac)})
        if nic.useVirtio:
            e(interface, 'model', None, attrib={'type': 'virtio'})
        else:
            e(interface, 'model', None, attrib={'type': 'e1000'})
        return interface

    @staticmethod
    def _add_qos_to_interface(interface, qos):
        if not qos.outboundBandwidth and not qos.inboundBandwidth:
            return

        bandwidth = e(interface, 'bandwidth')
        if qos.outboundBandwidth:
            e(bandwidth, 'outbound', None, {'average': str(qos.outboundBandwidth / 1024 / 8)})
        if qos.inboundBandwidth:
            e(bandwidth, 'inbound', None, {'average': str(qos.inboundBandwidth / 1024 / 8)})

def _stop_world():
    http.AsyncUirHandler.STOP_WORLD = True
    VmPlugin.queue.put("exit")

class VmPlugin(kvmagent.KvmAgent):
    KVM_START_VM_PATH = "/vm/start"
    KVM_STOP_VM_PATH = "/vm/stop"
    KVM_PAUSE_VM_PATH = "/vm/pause"
    KVM_RESUME_VM_PATH = "/vm/resume"
    KVM_REBOOT_VM_PATH = "/vm/reboot"
    KVM_DESTROY_VM_PATH = "/vm/destroy"
    KVM_ONLINE_CHANGE_CPUMEM_PATH = "/vm/online/changecpumem"
    KVM_ONLINE_INCREASE_CPU_PATH = "/vm/increase/cpu"
    KVM_ONLINE_INCREASE_MEMORY_PATH = "/vm/increase/mem"
    KVM_GET_CONSOLE_PORT_PATH = "/vm/getvncport"
    KVM_VM_SYNC_PATH = "/vm/vmsync"
    KVM_ATTACH_VOLUME = "/vm/attachdatavolume"
    KVM_DETACH_VOLUME = "/vm/detachdatavolume"
    KVM_MIGRATE_VM_PATH = "/vm/migrate"
    KVM_TAKE_VOLUME_SNAPSHOT_PATH = "/vm/volume/takesnapshot"
    KVM_TAKE_VOLUME_BACKUP_PATH = "/vm/volume/takebackup"
    KVM_BLOCK_STREAM_VOLUME_PATH = "/vm/volume/blockstream"
    KVM_TAKE_VOLUMES_SNAPSHOT_PATH = "/vm/volumes/takesnapshot"
    KVM_TAKE_VOLUMES_BACKUP_PATH = "/vm/volumes/takebackup"
    KVM_CANCEL_VOLUME_BACKUP_JOBS_PATH = "/vm/volume/cancel/backupjobs"
    KVM_MERGE_SNAPSHOT_PATH = "/vm/volume/mergesnapshot"
    KVM_LOGOUT_ISCSI_TARGET_PATH = "/iscsi/target/logout"
    KVM_LOGIN_ISCSI_TARGET_PATH = "/iscsi/target/login"
    KVM_ATTACH_NIC_PATH = "/vm/attachnic"
    KVM_DETACH_NIC_PATH = "/vm/detachnic"
    KVM_UPDATE_NIC_PATH = "/vm/updatenic"
    KVM_CREATE_SECRET = "/vm/createcephsecret"
    KVM_ATTACH_ISO_PATH = "/vm/iso/attach"
    KVM_DETACH_ISO_PATH = "/vm/iso/detach"
    KVM_VM_CHECK_STATE = "/vm/checkstate"
    KVM_VM_CHANGE_PASSWORD_PATH = "/vm/changepasswd"
    KVM_SET_VOLUME_BANDWIDTH = "/set/volume/bandwidth"
    KVM_DELETE_VOLUME_BANDWIDTH = "/delete/volume/bandwidth"
    KVM_GET_VOLUME_BANDWIDTH = "/get/volume/bandwidth"
    KVM_SET_NIC_QOS = "/set/nic/qos"
    KVM_GET_NIC_QOS = "/get/nic/qos"
    KVM_HARDEN_CONSOLE_PATH = "/vm/console/harden"
    KVM_DELETE_CONSOLE_FIREWALL_PATH = "/vm/console/deletefirewall"
    GET_PCI_DEVICES = "/pcidevice/get"
    HOT_PLUG_PCI_DEVICE = "/pcidevice/hotplug"
    HOT_UNPLUG_PCI_DEVICE = "/pcidevice/hotunplug"
    KVM_ATTACH_USB_DEVICE_PATH = "/vm/usbdevice/attach"
    KVM_DETACH_USB_DEVICE_PATH = "/vm/usbdevice/detach"
    CHECK_MOUNT_DOMAIN_PATH = "/check/mount/domain"
    KVM_RESIZE_VOLUME_PATH = "/volume/resize"

    VM_OP_START = "start"
    VM_OP_STOP = "stop"
    VM_OP_REBOOT = "reboot"
    VM_OP_MIGRATE = "migrate"
    VM_OP_DESTROY = "destroy"
    VM_OP_SUSPEND = "suspend"
    VM_OP_RESUME = "resume"

    timeout_object = linux.TimeoutObject()
    queue = Queue.Queue()

    if not os.path.exists(QMP_SOCKET_PATH):
        os.mkdir(QMP_SOCKET_PATH)

    def _record_operation(self, uuid, op):
        j = VmOperationJudger(op)
        self.timeout_object.put(uuid, j, 300)

    def _remove_operation(self, uuid):
        self.timeout_object.remove(uuid)

    def _get_operation(self, uuid):
        o = self.timeout_object.get(uuid)
        if not o:
            return None
        return o[0]

    def _start_vm(self, cmd):
        try:
            vm = get_vm_by_uuid_no_retry(cmd.vmInstanceUuid, False)

            if vm:
                if vm.state == Vm.VM_STATE_RUNNING:
                    raise kvmagent.KvmError(
                        'vm[uuid:%s, name:%s] is already running' % (cmd.vmInstanceUuid, vm.get_name()))
                else:
                    vm.destroy()

            vm = Vm.from_StartVmCmd(cmd)
            vm.start(cmd.timeout, cmd.createPaused)
        except libvirt.libvirtError as e:
            logger.warn(linux.get_exception_stacktrace())
            if "Device or resource busy" in str(e.message):
                raise kvmagent.KvmError(
                    'unable to start vm[uuid:%s, name:%s], libvirt error: %s' % (
                    cmd.vmInstanceUuid, cmd.vmName, str(e)))

            try:
                vm = get_vm_by_uuid(cmd.vmInstanceUuid)
                if vm and vm.state != Vm.VM_STATE_RUNNING:
                    raise kvmagent.KvmError(
                       'vm[uuid:%s, name:%s, state:%s] is not in running state, libvirt error: %s' % (
                        cmd.vmInstanceUuid, cmd.vmName, vm.state, str(e)))

            except kvmagent.KvmError:
                raise kvmagent.KvmError(
                    'unable to start vm[uuid:%s, name:%s], libvirt error: %s' % (cmd.vmInstanceUuid, cmd.vmName, str(e)))



    def _cleanup_iptable_chains(self, chain, data):
        if 'vnic' not in chain.name:
            return False

        vnic_name = chain.name.split('-')[0]
        if vnic_name not in data:
            logger.debug('clean up defunct vnic chain[%s]' % chain.name)
            return True
        return False

    @kvmagent.replyerror
    def attach_iso(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()

        vm = get_vm_by_uuid(cmd.vmUuid)
        vm.attach_iso(cmd)
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def detach_iso(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()

        vm = get_vm_by_uuid(cmd.vmUuid)
        vm.detach_iso(cmd)
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def attach_nic(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()

        vm = get_vm_by_uuid(cmd.vmUuid)
        vm.attach_nic(cmd)

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def detach_nic(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()

        vm = get_vm_by_uuid(cmd.vmUuid)
        vm.detach_nic(cmd)

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def update_nic(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()

        vm = get_vm_by_uuid(cmd.vmInstanceUuid)
        vm.update_nic(cmd)

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def start_vm(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = StartVmResponse()
        try:
            self._record_operation(cmd.vmInstanceUuid, self.VM_OP_START)

            self._start_vm(cmd)
            logger.debug('successfully started vm[uuid:%s, name:%s]' % (cmd.vmInstanceUuid, cmd.vmName))
            try:
                vm_pid = linux.find_vm_pid_by_uuid(cmd.vmInstanceUuid)
                linux.enable_process_coredump(vm_pid)
            except Exception as e:
                logger.warn("enable coredump for VM: %s: %s" % (cmd.vmInstanceUuid, str(e)))
        except kvmagent.KvmError as e:
            e_str = linux.get_exception_stacktrace()
            logger.warn(e_str)
            if "burst" in e_str and "Illegal" in e_str and "rate" in e_str:
                rsp.error = "QoS exceed max limit, please check and reset it in zstack"
            elif "cannot set up guest memory" in e_str:
                logger.warn('unable to start vm[uuid:%s], %s' % (cmd.vmInstanceUuid, e_str))
                rsp.error = "No enough physical memory for guest"
            else:
                rsp.error = e_str
            err = self.handle_vfio_irq_conflict(cmd.vmInstanceUuid)
            if err != "":
                rsp.error = "%s, details: %s" % (err, rsp.error)
            rsp.success = False
        return jsonobject.dumps(rsp)

    def get_vm_stat_with_ps(self, uuid):
        """In case libvirtd is stopped or misbehaved"""
        ret = shell.run("ps x | grep -w qemu | grep -v grep | grep -w -q %s" % uuid)
        if ret != 0:
            return Vm.VM_STATE_SHUTDOWN
        return Vm.VM_STATE_RUNNING

    @kvmagent.replyerror
    def check_vm_state(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        states = get_all_vm_states()
        rsp = CheckVmStateRsp()
        for uuid in cmd.vmUuids:
            s = states.get(uuid)
            if not s:
                s = self.get_vm_stat_with_ps(uuid)
            rsp.states[uuid] = s
        return jsonobject.dumps(rsp)

    def _escape(self, size):
        unit = size.strip().lower()[-1]
        num = size.strip()[:-1]
        units = {
            "g": lambda x: x * 1024,
            "m": lambda x: x,
            "k": lambda x: x / 1024,
        }
        return int(units[unit](int(num)))

    def _get_image_mb_size(self, image):
        backing = shell.call(
            'qemu-img info %s|grep "backing file:"|awk -F \'backing file:\' \'{print $2}\' ' % image).strip()
        size = shell.call('qemu-img info %s|grep "disk size:"|awk -F \'disk size:\' \'{print $2}\' ' % image).strip()
        if not backing:
            return self._escape(size)
        else:
            return self._get_image_mb_size(backing) + self._escape(size)

    def _get_volume_bandwidth_value(self, vm_uuid, device_id, mode):
        cmd_base = "virsh blkdeviotune %s %s" % (vm_uuid, device_id)
        if mode == "total":
            return shell.call('%s | grep -w total_bytes_sec | awk \'{print $2}\'' % cmd_base).strip()
        elif mode == "read":
            return shell.call('%s | grep -w read_bytes_sec | awk \'{print $3}\'' % cmd_base).strip()
        elif mode == "write":
            return shell.call('%s | grep -w write_bytes_sec | awk \'{print $2}\'' % cmd_base).strip()

    @kvmagent.replyerror
    def set_volume_bandwidth(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()
        vm = get_vm_by_uuid(cmd.vmUuid)
        _, device_id = vm._get_target_disk(cmd.volume)

        ## total and read/write of bytes_sec cannot be set at the same time
        ## http://confluence.zstack.io/pages/viewpage.action?pageId=42599772#comment-42600879
        cmd_base = "virsh blkdeviotune %s %s" % (cmd.vmUuid, device_id)
        if (cmd.mode == "total") or (cmd.mode is None):  # to set total(read/write reset)
            shell.call('%s --total_bytes_sec %s' % (cmd_base, cmd.totalBandwidth))
        elif cmd.mode == "read":  # to set read(write reserved, total reset)
            write_bytes_sec = self._get_volume_bandwidth_value(cmd.vmUuid, device_id, "write")
            shell.call('%s --read_bytes_sec %s --write_bytes_sec %s' % (cmd_base, cmd.readBandwidth, write_bytes_sec))
        elif cmd.mode == "write":  # to set write(read reserved, total reset)
            read_bytes_sec = self._get_volume_bandwidth_value(cmd.vmUuid, device_id, "read")
            shell.call('%s --read_bytes_sec %s --write_bytes_sec %s' % (cmd_base, read_bytes_sec, cmd.writeBandwidth))

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def delete_volume_bandwidth(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()
        vm = get_vm_by_uuid(cmd.vmUuid)
        _, device_id = vm._get_target_disk(cmd.volume)

        ## total and read/write of bytes_sec cannot be set at the same time
        ## http://confluence.zstack.io/pages/viewpage.action?pageId=42599772#comment-42600879
        cmd_base = "virsh blkdeviotune %s %s" % (cmd.vmUuid, device_id)
        is_total_mode = self._get_volume_bandwidth_value(cmd.vmUuid, device_id, "total") != "0"
        if cmd.mode == "all":  # to delete all(read/write reset)
            shell.call('%s --total_bytes_sec 0' % (cmd_base))
        elif (cmd.mode == "total") or (cmd.mode is None):  # to delete total
            if is_total_mode:
                shell.call('%s --total_bytes_sec 0' % (cmd_base))
        elif cmd.mode == "read":  # to delete read(write reserved, total reset)
            if not is_total_mode:
                write_bytes_sec = self._get_volume_bandwidth_value(cmd.vmUuid, device_id, "write")
                shell.call('%s --read_bytes_sec 0 --write_bytes_sec %s' % (cmd_base, write_bytes_sec))
        elif cmd.mode == "write":  # to delete write(read reserved, total reset)
            if not is_total_mode:
                read_bytes_sec = self._get_volume_bandwidth_value(cmd.vmUuid, device_id, "read")
                shell.call('%s --read_bytes_sec %s --write_bytes_sec 0' % (cmd_base, read_bytes_sec))

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def get_volume_bandwidth(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()
        vm = get_vm_by_uuid(cmd.vmUuid)
        _, device_id = vm._get_target_disk(cmd.volume)

        cmd_base = "virsh blkdeviotune %s %s" % (cmd.vmUuid, device_id)
        bandWidth = shell.call('%s | grep -w total_bytes_sec | awk \'{print $2}\'' % cmd_base).strip()
        bandWidthRead = shell.call('%s | grep -w read_bytes_sec | awk \'{print $3}\'' % cmd_base).strip()
        bandWidthWrite = shell.call('%s | grep -w write_bytes_sec | awk \'{print $2}\'' % cmd_base).strip()

        rsp.bandWidth = bandWidth if long(bandWidth) > 0 else -1
        rsp.bandWidthWrite = bandWidthWrite if long(bandWidthWrite) > 0 else -1
        rsp.bandWidthRead = bandWidthRead if long(bandWidthRead) > 0 else -1

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def set_nic_qos(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()
        try:
            if cmd.inboundBandwidth != -1:
                shell.call('virsh domiftune %s %s --inbound %s' % (cmd.vmUuid, cmd.internalName, cmd.inboundBandwidth/1024/8))
            if cmd.outboundBandwidth != -1:
                shell.call('virsh domiftune %s %s --outbound %s' % (cmd.vmUuid, cmd.internalName, cmd.outboundBandwidth/1024/8))
        except Exception as e:
            e_str = linux.get_exception_stacktrace()
            logger.warn(e_str)
            if "burst" in e_str and "Illegal" in e_str and "rate" in e_str:
                rsp.error = "QoS exceed the max limit, please check and reset it in zstack"
            else:
                rsp.error = e_str
            rsp.success = False
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def get_nic_qos(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()
        inbound = shell.call('virsh domiftune %s %s | grep "inbound.average:"|awk \'{print $2}\'' % (cmd.vmUuid, cmd.internalName)).strip()
        outbound = shell.call('virsh domiftune %s %s | grep "outbound.average:"|awk \'{print $2}\'' % (cmd.vmUuid, cmd.internalName)).strip()

        rsp.inbound = long(inbound) * 8 * 1024 if long(inbound) > 0 else -1
        rsp.outbound = long(outbound) * 8 * 1024 if long(outbound) > 0 else -1

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def check_mount_domain(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = CheckMountDomainRsp()

        finish_time = time.time() + (cmd.timeout / 1000)
        while time.time() < finish_time:
            try:
                logger.debug("check mount url: %s" % cmd.url)
                linux.is_valid_nfs_url(cmd.url)
                rsp.active = True
                return jsonobject.dumps(rsp)
            except Exception as err:
                if 'cannont resolve to ip address' in err.message:
                    logger.warn(err.message)
                    logger.warn('wait 1 seconds')
                else:
                    raise err
            time.sleep(1)
        rsp.active = False
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def change_vm_password(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = ChangeVmPasswordRsp()
        vm = get_vm_by_uuid(cmd.accountPerference.vmUuid, False)
        try:
            if not vm:
                raise kvmagent.KvmError('vm is not in running state.')
            else:
                vm.change_vm_password(cmd)
        except kvmagent.KvmError as e:
            rsp.error = str(e)
            rsp.success = False
        rsp.accountPerference = cmd.accountPerference
        rsp.accountPerference.accountPassword = "******"
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def harden_console(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = kvmagent.AgentResponse()

        vm = get_vm_by_uuid(cmd.vmUuid)
        vm.harden_console(cmd.hostManagementIp)

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def vm_sync(self, req):
        rsp = VmSyncResponse()
        rsp.states = get_all_vm_states()

        # In case of an reboot inside the VM.  Note that ZS will only define transient VM's.
        for uuid in rsp.states:
            if rsp.states[uuid] == Vm.VM_STATE_SHUTDOWN:
                rsp.states[uuid] = Vm.VM_STATE_RUNNING

        # Occasionally, virsh might not be able to list all VM instances with
        # uri=qemu://system.  To prevend this situation, we double check the
        # 'rsp.states' agaist QEMU process lists.
        output = bash.bash_o("ps x | grep -P -o 'qemu-kvm.*?-name\s+(guest=)?\K.*?,' | sed 's/.$//'").splitlines()
        for guest in output:
            if guest in rsp.states or guest.lower() == "ZStack Management Node VM".lower():
                continue
            logger.warn('guest [%s] not found in virsh list' % guest)
            rsp.states[guest] = Vm.VM_STATE_RUNNING

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def online_increase_mem(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = IncreaseMemoryResponse()

        if IS_AARCH64:
            rsp.error = 'increase memory of vm[uuid:%s] on arrch64 is not supported yet' % cmd.vmUuid
            rsp.success = False
            return jsonobject.dumps(rsp)

        try:
            vm = get_vm_by_uuid(cmd.vmUuid)
            memory_size = cmd.memorySize
            vm.hotplug_mem(memory_size)
            vm = get_vm_by_uuid(cmd.vmUuid)
            rsp.memorySize = vm.get_memory()
            logger.debug('successfully increase memory of vm[uuid:%s] to %s Kib' % (cmd.vmUuid, vm.get_memory()))
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def online_increase_cpu(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = IncreaseCpuResponse()

        if IS_AARCH64:
            rsp.error = 'increase cpu of vm[uuid:%s] on arrch64 is not supported yet' % cmd.vmUuid
            rsp.success = False
            return jsonobject.dumps(rsp)

        try:
            vm = get_vm_by_uuid(cmd.vmUuid)
            cpu_num = cmd.cpuNum
            vm.hotplug_cpu(cpu_num)
            vm = get_vm_by_uuid(cmd.vmUuid)
            rsp.cpuNum = vm.get_cpu_num()
            logger.debug('successfully increase cpu number of vm[uuid:%s] to %s' % (cmd.vmUuid, vm.get_cpu_num()))
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def online_change_cpumem(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = ChangeCpuMemResponse()
        try:
            vm = get_vm_by_uuid(cmd.vmUuid)
            cpu_num = cmd.cpuNum
            memory_size = cmd.memorySize
            vm.hotplug_mem(memory_size)
            vm.hotplug_cpu(cpu_num)
            vm = get_vm_by_uuid(cmd.vmUuid)
            rsp.cpuNum = vm.get_cpu_num()
            rsp.memorySize = vm.get_memory()
            logger.debug('successfully add cpu and memory on vm[uuid:%s]' % (cmd.vmUuid))
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False
        return jsonobject.dumps(rsp)

    def get_vm_console_info(self, vmUuid):
        try:
            vm = get_vm_by_uuid(vmUuid)
            proto, port = vm.get_console_protocol(), vm.get_console_port()
            if port > 0:
                return proto, port

            # Occasionally, 'virsh list' would list nothing but conn.lookupByName()
            # can find the VM and dom.XMLDesc(0) will return VNC port '-1'.
            err = 'libvirt failed to get console port for VM %s' % vmUuid
            logger.warn(err)
            raise kvmagent.KvmError(err)
        except kvmagent.KvmError as e:
            proto, port = get_console_without_libvirt(vmUuid)
            if port:
                return proto, port
            raise e

    @kvmagent.replyerror
    def get_console_port(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = GetVncPortResponse()
        try:
            proto, port = self.get_vm_console_info(cmd.vmUuid)
            rsp.port = port
            rsp.protocol = proto
            logger.debug('successfully get vnc port[%s] of vm[uuid:%s]' % (port, cmd.vmUuid))
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    def _stop_vm(self, cmd):
        try:
            vm = get_vm_by_uuid(cmd.uuid)

            if str(cmd.type) == "cold":
                vm.stop(graceful=False)
            else:
                vm.stop(timeout=cmd.timeout / 2)
        except kvmagent.KvmError as e:
            logger.debug(linux.get_exception_stacktrace())
        finally:
            # libvirt is not reliable, c.f. ZSTAC-15412
            self.kill_vm(cmd.uuid)

    def kill_vm(self, vm_uuid):
        output = bash.bash_o("ps x | grep -P -o 'qemu-kvm.*?-name\s+(guest=)?\K%s,' | sed 's/.$//'" % vm_uuid)

        if vm_uuid not in output:
            return

        logger.debug('killing vm %s' % vm_uuid)
        vm_pid = linux.find_vm_pid_by_uuid(vm_uuid)
        linux.kill_process(vm_pid)

    @kvmagent.replyerror
    def stop_vm(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = StopVmResponse()
        try:
            self._record_operation(cmd.uuid, self.VM_OP_STOP)

            self._stop_vm(cmd)
            logger.debug("successfully stopped vm[uuid:%s]" % cmd.uuid)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def pause_vm(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        try:
            self._record_operation(cmd.uuid, self.VM_OP_SUSPEND)
            rsp = PauseVmResponse()
            vm = get_vm_by_uuid(cmd.uuid)
            vm.pause()
            logger.debug('successfully, pause vm [uuid:%s]' % cmd.uuid)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def resume_vm(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        try:
            self._record_operation(cmd.uuid, self.VM_OP_RESUME)
            rsp = ResumeVmResponse()
            vm = get_vm_by_uuid(cmd.uuid)
            vm.resume()
            logger.debug('successfully, resume vm [uuid:%s]' % cmd.uuid)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def reboot_vm(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = RebootVmResponse()
        try:
            self._record_operation(cmd.uuid, self.VM_OP_REBOOT)

            vm = get_vm_by_uuid(cmd.uuid)
            vm.reboot(cmd)
            logger.debug('successfully, reboot vm[uuid:%s]' % cmd.uuid)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def destroy_vm(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = DestroyVmResponse()
        try:
            self._record_operation(cmd.uuid, self.VM_OP_DESTROY)

            vm = get_vm_by_uuid(cmd.uuid, False)
            if vm:
                vm.destroy()
                logger.debug('successfully destroyed vm[uuid:%s]' % cmd.uuid)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def attach_data_volume(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = AttachDataVolumeResponse()
        try:
            volume = cmd.volume
            vm = get_vm_by_uuid(cmd.vmInstanceUuid)
            if vm.state != Vm.VM_STATE_RUNNING:
                raise kvmagent.KvmError(
                    'unable to attach volume[%s] to vm[uuid:%s], vm must be running' % (volume.installPath, vm.uuid))
            vm.attach_data_volume(cmd.volume, cmd.addons)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        touchQmpSocketWhenExists(cmd.vmInstanceUuid)
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def detach_data_volume(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = DetachDataVolumeResponse()
        try:
            volume = cmd.volume
            vm = get_vm_by_uuid(cmd.vmInstanceUuid)
            if vm.state != Vm.VM_STATE_RUNNING:
                raise kvmagent.KvmError(
                    'unable to detach volume[%s] to vm[uuid:%s], vm must be running' % (volume.installPath, vm.uuid))
            vm.detach_data_volume(volume)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def migrate_vm(self, req):
        @linux.retry(times=3, sleep_time=1)
        def get_connect(srcHostIP):
            return libvirt.open('qemu+tcp://{0}/system'.format(srcHostIP))

        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = MigrateVmResponse()
        try:
            self._record_operation(cmd.vmUuid, self.VM_OP_MIGRATE)

            if cmd.migrateFromDestination:
                conn = get_connect(cmd.srcHostIp)
                if conn is None:
                    logger.warn('unable to connect qemu on host {0}'.format(cmd.srcHostIp))
                    raise kvmagent.KvmError('unable to connect qemu on host %s' % (cmd.srcHostIp))

                vm = get_vm_by_uuid(cmd.vmUuid, False, conn)
                if vm is None:
                    conn.close()
                    logger.warn('unable to find vm {0} on host {1}'.format(cmd.vmUuid, cmd.srcHostIp))
                    raise kvmagent.KvmError('unable to find vm %s on host %s' % (cmd.vmUuid, cmd.srcHostIp))

                vm.migrate(cmd)
                conn.close()
            else:
                vm = get_vm_by_uuid(cmd.vmUuid)
                vm.migrate(cmd)

        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def merge_snapshot_to_volume(self, req):
        rsp = MergeSnapshotRsp()
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        vm = get_vm_by_uuid(cmd.vmUuid, exception_if_not_existing=True)

        if vm.state != vm.VM_STATE_RUNNING:
            rsp.error = 'vm[uuid:%s] is not running, cannot do live snapshot chain merge' % vm.uuid
            rsp.success = False
            return jsonobject.dumps(rsp)

        vm.merge_snapshot(cmd)
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def take_volumes_snapshots(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])  # type: TakeSnapshotsCmd
        rsp = TakeSnapshotsResponse()  # type: TakeSnapshotsResponse

        for snapshot_job in cmd.snapshotJobs:
            if snapshot_job.vmInstanceUuid != cmd.snapshotJobs[0].vmInstanceUuid:
                raise kvmagent.KvmError("can not take snapshot on multiple vms[%s and %s]" %
                                        snapshot_job.vmInstanceUuid, cmd.snapshotJobs[0].vmInstanceUuid)
            if snapshot_job.live != cmd.snapshotJobs[0].live:
                raise kvmagent.KvmError("can not take snapshot on different live status")

        def makedir_if_need(new_path):
            dirname = os.path.dirname(new_path)
            if not os.path.exists(dirname):
                os.makedirs(dirname, 0755)

        def get_size(install_path):
            """
            :rtype: long
            """
            size = linux.get_local_file_disk_usage(install_path)
            if size is None or size == 0:
                size = linux.qcow2_virtualsize(install_path)
            return size

        def take_full_snapshot_by_qemu_img_convert(previous_install_path, install_path, new_volume_install_path):
            """
            :rtype: (str, str, long)
            """
            makedir_if_need(install_path)
            linux.create_template(previous_install_path, install_path)
            new_volume_path = new_volume_install_path if new_volume_install_path is not None else os.path.join(os.path.dirname(install_path), '{0}.qcow2'.format(uuidhelper.uuid()))
            makedir_if_need(new_volume_path)
            linux.qcow2_clone_with_cmd(install_path, new_volume_path, cmd)

            return install_path, new_volume_path, get_size(install_path)

        def take_delta_snapshot_by_qemu_img_convert(previous_install_path, install_path, new_volume_install_path):
            """
            :rtype: (str, str, long)
            """
            new_volume_path = new_volume_install_path if new_volume_install_path is not None else os.path.join(os.path.dirname(install_path), '{0}.qcow2'.format(uuidhelper.uuid()))
            makedir_if_need(new_volume_path)
            linux.qcow2_clone_with_cmd(previous_install_path, new_volume_path, cmd)

            return previous_install_path, new_volume_path, get_size(install_path)

        vm = get_vm_by_uuid(cmd.snapshotJobs[0].vmInstanceUuid, exception_if_not_existing=False)
        try:
            if vm and vm.state not in vm.ALLOW_SNAPSHOT_STATE:
                raise kvmagent.KvmError(
                    'unable to take snapshot on vm[uuid:{0}] volume[id:{1}], '
                    'because vm is not in [{2}], current state is {3}'.format(
                        vm.uuid, cmd.snapshotJobs[0].deviceId, vm.ALLOW_SNAPSHOT_STATE, vm.state))

            if vm and (vm.state == vm.VM_STATE_RUNNING or vm.state == vm.VM_STATE_PAUSED):
                rsp.snapshots = vm.take_live_volumes_delta_snapshots(cmd.snapshotJobs)
            else:
                if vm and cmd.snapshotJobs[0].live is True:
                    raise kvmagent.KvmError("expected live snapshot but vm[%s] state is %s" %
                                            vm.uuid, vm.state)
                elif not vm and cmd.snapshotJobs[0].live is True:
                    raise kvmagent.KvmError("expected live snapshot but can not find vm[%s]" %
                                            cmd.snapshotJobs[0].vmInstanceUuid)

                for snapshot_job in cmd.snapshotJobs:
                    if snapshot_job.full:
                        rsp.snapshots.append(VolumeSnapshotResultStruct(
                            snapshot_job.volumeUuid, *take_full_snapshot_by_qemu_img_convert(
                                snapshot_job.previousInstallPath, snapshot_job.installPath, snapshot_job.newVolumeInstallPath)))
                    else:
                        rsp.snapshots.append(VolumeSnapshotResultStruct(
                            snapshot_job.volumeUuid, *take_delta_snapshot_by_qemu_img_convert(
                                snapshot_job.previousInstallPath, snapshot_job.installPath, snapshot_job.newVolumeInstallPath)))

        except kvmagent.KvmError as error:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(error)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def take_volume_snapshot(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = TakeSnapshotResponse()

        def makedir_if_need(new_path):
            dirname = os.path.dirname(new_path)
            if not os.path.exists(dirname):
                os.makedirs(dirname, 0755)

        def take_full_snapshot_by_qemu_img_convert(previous_install_path, install_path):
            makedir_if_need(install_path)
            linux.create_template(previous_install_path, install_path)
            new_volume_path = cmd.newVolumeInstallPath if cmd.newVolumeInstallPath is not None else os.path.join(os.path.dirname(install_path), '{0}.qcow2'.format(uuidhelper.uuid()))
            makedir_if_need(new_volume_path)
            linux.qcow2_clone_with_cmd(install_path, new_volume_path, cmd)
            return install_path, new_volume_path

        def take_delta_snapshot_by_qemu_img_convert(previous_install_path, install_path):
            new_volume_path = cmd.newVolumeInstallPath if cmd.newVolumeInstallPath is not None else os.path.join(os.path.dirname(install_path), '{0}.qcow2'.format(uuidhelper.uuid()))
            makedir_if_need(new_volume_path)
            linux.qcow2_clone_with_cmd(previous_install_path, new_volume_path, cmd)
            return previous_install_path, new_volume_path

        try:
            if not cmd.vmUuid:
                if cmd.fullSnapshot:
                    rsp.snapshotInstallPath, rsp.newVolumeInstallPath = take_full_snapshot_by_qemu_img_convert(
                        cmd.volumeInstallPath, cmd.installPath)
                else:
                    rsp.snapshotInstallPath, rsp.newVolumeInstallPath = take_delta_snapshot_by_qemu_img_convert(
                        cmd.volumeInstallPath, cmd.installPath)

            else:
                vm = get_vm_by_uuid(cmd.vmUuid, exception_if_not_existing=False)

                if vm and vm.state != vm.VM_STATE_RUNNING and vm.state != vm.VM_STATE_SHUTDOWN and vm.state != vm.VM_STATE_PAUSED:
                    raise kvmagent.KvmError(
                        'unable to take snapshot on vm[uuid:{0}] volume[id:{1}], because vm is not Running, Stopped or Paused, current state is {2}'.format(
                            vm.uuid, cmd.volume.deviceId, vm.state))

                if vm and (vm.state == vm.VM_STATE_RUNNING or vm.state == vm.VM_STATE_PAUSED):
                    rsp.snapshotInstallPath, rsp.newVolumeInstallPath = vm.take_volume_snapshot(cmd.volume,
                                                                                                cmd.installPath,
                                                                                                cmd.fullSnapshot)
                else:
                    if cmd.fullSnapshot:
                        rsp.snapshotInstallPath, rsp.newVolumeInstallPath = take_full_snapshot_by_qemu_img_convert(
                            cmd.volumeInstallPath, cmd.installPath)
                    else:
                        rsp.snapshotInstallPath, rsp.newVolumeInstallPath = take_delta_snapshot_by_qemu_img_convert(
                            cmd.volumeInstallPath, cmd.installPath)

                if cmd.fullSnapshot:
                    logger.debug(
                        'took full snapshot on vm[uuid:{0}] volume[id:{1}], snapshot path:{2}, new volulme path:{3}'.format(
                            cmd.vmUuid, cmd.volume.deviceId, rsp.snapshotInstallPath, rsp.newVolumeInstallPath))
                else:
                    logger.debug(
                        'took delta snapshot on vm[uuid:{0}] volume[id:{1}], snapshot path:{2}, new volulme path:{3}'.format(
                            cmd.vmUuid, cmd.volume.deviceId, rsp.snapshotInstallPath, rsp.newVolumeInstallPath))

            rsp.size = linux.get_local_file_disk_usage(rsp.snapshotInstallPath)
            if rsp.size is None or rsp.size == 0:
                if rsp.snapshotInstallPath.startswith("/dev/"):
                    rsp.size = int(lvm.get_lv_size(rsp.snapshotInstallPath))
                else:
                    rsp.size = linux.qcow2_virtualsize(rsp.snapshotInstallPath)
        except kvmagent.KvmError as e:
            logger.warn(linux.get_exception_stacktrace())
            rsp.error = str(e)
            rsp.success = False

        touchQmpSocketWhenExists(cmd.vmUuid)
        return jsonobject.dumps(rsp)

    def push_backing_files(self, isc, hostname, drivertype, source):
        if drivertype != 'qcow2':
            return None

        bf = linux.qcow2_get_backing_file(source.file_)
        if bf:
            imf = isc.upload_image(hostname, bf)
            return imf

        return None

    def do_cancel_backup_jobs(self, cmd):
        isc = ImageStoreClient()
        isc.stop_backup_jobs(cmd.vmUuid)

    # returns list[VolumeBackupInfo]
    def do_take_volumes_backup(self, cmd, target_disks, bitmaps, dstdir):
        isc = ImageStoreClient()
        backupArgs = {}
        parents = {}
        speed = 0

        if cmd.volumeWriteBandwidth:
            speed = cmd.volumeWriteBandwidth

        device_ids = [volume.deviceId for volume in cmd.volumes]
        for deviceId in device_ids:
            target_disk = target_disks[deviceId]
            drivertype = target_disk.driver.type_
            nodename = 'drive-' + target_disk.alias.name_
            source = target_disk.source
            bitmap = bitmaps[deviceId]

            def get_backup_args():
                if bitmap:
                    return bitmap, 'full' if cmd.mode == 'full' else 'auto', nodename, speed

                bm = 'zsbitmap%d' % deviceId
                if cmd.mode == 'full':
                    return bm, 'full', nodename, speed

                imf = self.push_backing_files(isc, cmd.hostname, drivertype, source)
                if not imf:
                    return bm, 'full', nodename, speed

                parent = isc._build_install_path(imf.name, imf.id)
                parents[deviceId] = parent
                return bm, 'top', nodename, speed

            backupArgs[deviceId] = get_backup_args()

        logger.info('taking backup for vm: %s' % cmd.vmUuid)
        res = isc.backup_volumes(cmd.vmUuid, backupArgs.values(), dstdir)
        logger.info('completed backup for vm: %s' % cmd.vmUuid)

        backres = jsonobject.loads(res)
        bkinfos = []

        for deviceId in device_ids:
            nodename = backupArgs[deviceId][2]
            nodebak = backres[nodename]

            installPath = None
            if nodebak.mode == 'incremental':
                installPath = self.getLastBackup(deviceId, cmd.backupInfos)
            else:
                installPath = parents.get(deviceId)

            info = VolumeBackupInfo(deviceId,
                    backupArgs[deviceId][0],
                    nodebak.backupFile,
                    installPath)

            if nodebak.mode == 'top' and info.parentInstallPath is None:
                target_disk = target_disks[deviceId]
                drivertype = target_disk.driver.type_
                source = target_disk.source
                imf = self.push_backing_files(isc, cmd.hostname, drivertype, source)
                if imf:
                    parent = isc._build_install_path(imf.name, imf.id)
                    info.parentInstallPath = parent

            bkinfos.append(info)

        return bkinfos

    # returns tuple: (bitmap, parent)
    def do_take_volume_backup(self, cmd, drivertype, nodename, source, dest):
        isc = ImageStoreClient()
        bitmap = None
        parent = None
        mode = None
        topoverlay = None
        speed = 0

        if drivertype == 'qcow2':
            topoverlay = source.file_

        def get_parent_bitmap_mode():
            if cmd.bitmap:
                return None, cmd.bitmap, 'full' if cmd.mode == 'full' else 'auto'

            bitmap = 'zsbitmap%d' % (cmd.volume.deviceId)
            if drivertype != 'qcow2':
                return None, bitmap, 'full'

            if cmd.mode == 'full':
                return None, bitmap, 'full'

            bf = linux.qcow2_get_backing_file(topoverlay)
            if not bf:
                return None, bitmap, 'full'

            imf = isc.upload_image(cmd.hostname, bf)
            parent = isc._build_install_path(imf.name, imf.id)
            return parent, bitmap, 'top'

        parent, bitmap, mode = get_parent_bitmap_mode()

        if cmd.volumeWriteBandwidth:
            speed = cmd.volumeWriteBandwidth

        mode = isc.backup_volume(cmd.vmUuid, nodename, bitmap, mode, dest, speed)
        logger.info('finished backup volume with mode: %s' % mode)

        if mode == 'incremental':
            return bitmap, cmd.lastBackup

        if mode == 'top' and parent is None and topoverlay != None:
            bf = linux.qcow2_get_backing_file(topoverlay)
            imf = isc.upload_image(cmd.hostname, bf)
            parent = isc._build_install_path(imf.name, imf.id)

        return bitmap, parent

    def getLastBackup(self, deviceId, backupInfos):
        for info in backupInfos:
            if info.deviceId == deviceId:
                return info.lastBackup

        return None

    def getBitmap(self, deviceId, backupInfos):
        for info in backupInfos:
            if info.deviceId == deviceId:
                return info.bitmap

        return None

    @kvmagent.replyerror
    def cancel_backup_jobs(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = TakeVolumesBackupsResponse()

        try:
            vm = get_vm_by_uuid(cmd.vmUuid, exception_if_not_existing=False)
            if not vm:
                raise kvmagent.KvmError("vm[uuid: %s] not found by libvirt" % vm.uuid)

            self.do_cancel_backup_jobs(cmd)
        except kvmagent.KvmError as e:
            logger.warn("cancel vm[uuid:%s] backup failed: %s" % (cmd.vmUuid, str(e)))
            rsp.error = str(e)
            rsp.success = False

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def take_volumes_backups(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = TakeVolumesBackupsResponse()
        d = tempfile.mkdtemp() # temporary mount point

        try:
            vm = get_vm_by_uuid(cmd.vmUuid, exception_if_not_existing=False)
            if not vm:
                raise kvmagent.KvmError("vm[uuid: %s] not found by libvirt" % vm.uuid)

            if not cmd.networkWriteBandwidth:
                if 0 != linux.sshfs_mount(cmd.username, cmd.hostname, cmd.sshPort, cmd.password, cmd.uploadDir, d):
                    raise kvmagent.KvmError("failed to prepare backup space for [vm:%s]" % cmd.vmUuid)
            else:
                if 0 != linux.sshfs_mount(cmd.username, cmd.hostname, cmd.sshPort, cmd.password, cmd.uploadDir, d, cmd.networkWriteBandwidth):
                    raise kvmagent.KvmError("failed to prepare backup space for [vm:%s]" % cmd.vmUuid)

            target_disks = {}
            for volume in cmd.volumes:
                target_disk, _ = vm._get_target_disk(volume)
                target_disks[volume.deviceId] = target_disk

            bitmaps = {}
            device_ids = [volume.deviceId for volume in cmd.volumes]
            for deviceId in device_ids:
                bitmap = self.getBitmap(deviceId, cmd.backupInfos)
                bitmaps[deviceId] = bitmap

            res = self.do_take_volumes_backup(cmd,
                    target_disks,
                    bitmaps,
                    d)

            for r in res:
                r.backupFile = os.path.join(cmd.uploadDir, r.backupFile)
            rsp.backupInfos = res

        except Exception as e:
            content = traceback.format_exc()
            logger.warn("take vm[uuid:%s] backup failed: %s\n%s" % (cmd.vmUuid, str(e), content))
            rsp.error = str(e)
            rsp.success = False
        finally:
            for i in xrange(6):
                linux.fumount(d, 5)
            linux.rmdir_if_empty(d)

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def take_volume_backup(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = TakeVolumeBackupResponse()
        d = tempfile.mkdtemp()
        fname = uuidhelper.uuid()+".qcow2"

        try:
            vm = get_vm_by_uuid(cmd.vmUuid, exception_if_not_existing=False)
            if not vm:
                raise kvmagent.KvmError("vm[uuid: %s] not found by libvirt" % vm.uuid)

            if not cmd.networkWriteBandwidth:
                if 0 != linux.sshfs_mount(cmd.username, cmd.hostname, cmd.sshPort, cmd.password, cmd.uploadDir, d):
                    raise kvmagent.KvmError(
                        "failed to prepare backup space for [vm:%s,deviceId:%d]" % (cmd.vmUuid, cmd.volume.deviceId))
            else:
                if 0 != linux.sshfs_mount(cmd.username, cmd.hostname, cmd.sshPort, cmd.password, cmd.uploadDir, d, cmd.networkWriteBandwidth):
                    raise kvmagent.KvmError(
                        "failed to prepare backup space for [vm:%s,deviceId:%d]" % (cmd.vmUuid, cmd.volume.deviceId))

            target_disk, _ = vm._get_target_disk(cmd.volume)
            bitmap, parent = self.do_take_volume_backup(cmd,
                    target_disk.driver.type_, # 'qcow2' etc.
                    'drive-' + target_disk.alias.name_,  # 'virtio-disk0' etc.
                    target_disk.source,
                    os.path.join(d, fname))
            logger.info('finished backup volume with parent: %s' % parent)
            rsp.bitmap = bitmap
            rsp.parentInstallPath = parent
            rsp.backupFile = os.path.join(cmd.uploadDir, fname)

        except Exception as e:
            content = traceback.format_exc()
            logger.warn("take volume backup failed: " + str(e) + '\n' + content)
            rsp.error = str(e)
            rsp.success = False

        finally:
            for i in xrange(6):
                linux.fumount(d, 5)
            linux.rmdir_if_empty(d)

        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def block_stream(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = BlockStreamResponse()
        if not cmd.vmUuid:
            rsp.success = True
            return jsonobject.dumps(rsp)

        vm = get_vm_by_uuid(cmd.vmUuid, exception_if_not_existing=False)
        if not vm:
            rsp.success = True
            return jsonobject.dumps(rsp)

        vm.block_stream_disk(cmd.volume)
        rsp.success = True
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    @lock.lock('iscsiadm')
    def logout_iscsi_target(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        shell.call(
            'iscsiadm  -m node  --targetname "%s" --portal "%s:%s" --logout' % (cmd.target, cmd.hostname, cmd.port))
        rsp = LogoutIscsiTargetRsp()
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def login_iscsi_target(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])

        login = IscsiLogin()
        login.server_hostname = cmd.hostname
        login.server_port = cmd.port
        login.chap_password = cmd.chapPassword
        login.chap_username = cmd.chapUsername
        login.target = cmd.target
        login.login()

        return jsonobject.dumps(LoginIscsiTargetRsp())

    @kvmagent.replyerror
    def delete_console_firewall_rule(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        vir = VncPortIptableRule()
        vir.vm_internal_id = cmd.vmInternalId
        vir.host_ip = cmd.hostManagementIp
        vir.delete()

        return jsonobject.dumps(kvmagent.AgentResponse())

    @kvmagent.replyerror
    def create_ceph_secret_key(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        VmPlugin._create_ceph_secret_key(cmd.userKey, cmd.uuid)
        return jsonobject.dumps(kvmagent.AgentResponse())

    @staticmethod
    def _create_ceph_secret_key(userKey, uuid):
        sh_cmd = shell.ShellCmd('virsh secret-get-value %s' % uuid)
        sh_cmd(False)
        if sh_cmd.stdout.strip() == userKey:
            return
        elif sh_cmd.return_code == 0:
            shell.call('virsh secret-set-value %s %s' % (uuid, userKey))
            return

        # for some reason, ceph doesn't work with the secret created by libvirt
        # we have to use the command line here
        content = '''
<secret ephemeral='yes' private='no'>
    <uuid>%s</uuid>
    <usage type='ceph'>
        <name>%s</name>
    </usage>
</secret>
    ''' % (uuid, uuid)

        spath = linux.write_to_temp_file(content)
        try:
            o = shell.call("virsh secret-define %s" % spath)
            o = o.strip(' \n\t\r')
            _, generateuuid, _ = o.split()
            shell.call('virsh secret-set-value %s %s' % (generateuuid, userKey))
        finally:
            os.remove(spath)

    @staticmethod
    def add_amdgpu_to_blacklist():
        r_amd = bash.bash_r("grep -E 'modprobe.blacklist.*amdgpu' /etc/default/grub")
        if r_amd != 0:
            r_amd, o_amd, e_amd = bash.bash_roe("sed -i 's/radeon/amdgpu,radeon/g' /etc/default/grub")
            if r_amd != 0:
                return False, "%s %s" % (e_amd, o_amd)
            r_amd, o_amd, e_amd = bash.bash_roe("grub2-mkconfig -o /boot/grub2/grub.cfg")
            if r_amd != 0:
                return False, "%s %s" % (e_amd, o_amd)
            r_amd, o_amd, e_amd = bash.bash_roe("grub2-mkconfig -o /etc/grub2-efi.cfg")
            if r_amd != 0:
                return False, "%s %s" % (e_amd, o_amd)

        return True, None

    @kvmagent.replyerror
    @in_bash
    def get_pci_info(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = GetPciDevicesResponse()
        r, o, e = bash.bash_roe("grep -E 'intel_iommu(\ )*=(\ )*on' /etc/default/grub")
        # Note(WeiW): Skip config iommu if enable iommu is false
        if cmd.enableIommu is False:
            r = 0
        # Note(WeiW): Add amdgpu to blacklist for upgrade
        elif r == 0:
            success, error = self.add_amdgpu_to_blacklist()
            if success is False:
                rsp.success = False
                rsp.error = error
                return jsonobject.dumps(rsp)

        if r != 0:
            r, o, e = bash.bash_roe("sed -i '/GRUB_CMDLINE_LINUX/s/\"$/ intel_iommu=on modprobe.blacklist=snd_hda_intel,amd76x_edac,vga16fb,nouveau,rivafb,nvidiafb,rivatv,amdgpu,radeon\"/g' /etc/default/grub")
            if r != 0:
                rsp.success = False
                rsp.error = "%s %s" % (e, o)
                return jsonobject.dumps(rsp)
            r, o, e = bash.bash_roe("grub2-mkconfig -o /boot/grub2/grub.cfg")
            if r != 0:
                rsp.success = False
                rsp.error = "%s %s" % (e, o)
                return jsonobject.dumps(rsp)
            r, o, e = bash.bash_roe("grub2-mkconfig -o /etc/grub2-efi.cfg")
            if r != 0:
                rsp.success = False
                rsp.error = "%s %s" % (e, o)
                return jsonobject.dumps(rsp)
            r, o, e = bash.bash_roe("modprobe vfio && modprobe vfio-pci")
            if r != 0:
                rsp.success = False
                rsp.error = "%s %s" % (e, o)
                return jsonobject.dumps(rsp)
        r_bios, o_bios, e_bios = bash.bash_roe("find /sys -iname dmar*")
        r_kernel, o_kernel, e_kernel = bash.bash_roe("grep 'intel_iommu=on' /proc/cmdline")
        if o_bios != '' and r_kernel == 0:
            rsp.hostIommuStatus = True
        else:
            rsp.hostIommuStatus = False
        r, o, e = bash.bash_roe("lspci -mmnnv")
        if r!= 0:
            rsp.success = False
            rsp.error = "%s %s" % (e, o)
        else:
            rsp.pciDevicesInfo = o
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    @in_bash
    def hot_plug_pci_device(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = HotPlugPciDeviceRsp()
        addr = cmd.pciDeviceAddress
        domain = hex(0) if len(addr.split(":")) == 2 else hex(int(addr.split(":")[0], 16))
        bus = hex(int(addr.split(":")[-2], 16))
        slot = hex(int(addr.split(":")[-1].split(".")[0], 16))
        function = hex(int(addr.split(":")[-1].split(".")[1], 16))
        content = '''
<hostdev mode='subsystem' type='pci' managed='yes'>
     <driver name='vfio'/>
     <source>
       <address type='pci' domain='%s' bus='%s' slot='%s' function='%s'/>
     </source>
</hostdev>''' % (domain, bus, slot, function)
        spath = linux.write_to_temp_file(content)
        r, o, e = bash.bash_roe("virsh attach-device %s %s" % (cmd.vmUuid, spath))
        logger.debug("attach %s to %s finished, %s, %s" % (
            spath, cmd.vmUuid, o, e))
        if r!= 0:
            rsp.success = False
            err = self.handle_vfio_irq_conflict_with_addr(cmd.vmUuid, addr)
            if err == "":
                rsp.error = "%s %s" % (e, o)
            else:
                rsp.error = "%s, details: %s %s" % (err, e, o)
        return jsonobject.dumps(rsp)

    @in_bash
    def handle_vfio_irq_conflict_with_addr(self, vmUuid, addr):
        logger.debug("check irq conflict with %s, %s" % (vmUuid, addr))
        cmd = ("tail -n 5 /var/log/libvirt/qemu/%s.log | grep -E 'vfio: Error: Failed to setup INTx fd: Device or resource busy'" %
                vmUuid)
        r, o, e = bash.bash_roe(cmd)
        if r != 0:
            return ""
        cmd = "lspci -vs %s | grep IRQ | awk '{print $5}' | grep -E -o '[[:digit:]]+'" % addr
        r, o, e = bash.bash_roe(cmd)
        if o == "":
            return "can not get irq"
        hostname = bash.bash_o("hostname -f")

        cmd = "devices=`find /sys/devices/ -iname 'irq' | grep pci | xargs grep %s | grep -v '%s' | awk -F '/' '{ print \"/\"$2\"/\"$3\"/\"$4\"/\"$5 }' | sort | uniq`;" % (o.strip(), addr) + \
              " for dev in $devices; do wc -l $dev/msi_bus; done | grep -E '^.*0 /sys' | awk -F '/' '{ print \"/\"$2\"/\"$3\"/\"$4\"/\"$5 }'"
        r, o, e = bash.bash_roe(cmd)
        if o == "":
            return "there are irq conflict, but zstack can not get irq conflict device, you need fix it manually"
        ret = ""
        names = ""
        for dev in o.splitlines():
            if dev.strip() != "":
                ret += "echo 1 > %s/remove; " % dev
                cmd = "lspci -s %s" % dev.split('/')[-1]
                r, o, e = bash.bash_roe(cmd)
                names += o.strip()

        return "WARN: found irq conflict for pci device addr %s, please execute '%s', and then try to passthrough again. Please noted, the above command will remove the conflicted devices(%s) from system, ONLY reboot can bring the device back to service." % \
               (addr, ret, names)

    @in_bash
    def handle_vfio_irq_conflict(self, vmUuid):
        cmd = ("tail -n 5 /var/log/libvirt/qemu/%s.log | grep -E 'qemu.*vfio: Error: Failed to setup INTx fd: Device or resource busy' | awk -F'[=,]' '{ print $3 }'" %
                vmUuid)
        r, o, e = bash.bash_roe(cmd)
        if r != 0:
            return ""
        return self.handle_vfio_irq_conflict_with_addr(vmUuid, o.strip())

    @kvmagent.replyerror
    @in_bash
    def hot_unplug_pci_device(self, req):
        @linux.retry(3, 3)
        def find_pci_device(vmUuid, pciDeviceAddress):
            bus = pciDeviceAddress.split(":")[0]
            slot = pciDeviceAddress.split(":")[1].split(".")[0]
            func = pciDeviceAddress.split(".")[-1]

            cmd = """virsh dumpxml %s | grep -A3 -E '<hostdev.*pci' | grep "<address domain='0x0000' bus='0x%s' slot='0x%s' function='0x%s'/>" """ % \
                  (vmUuid, bus, slot, func)
            r, o, e = bash.bash_roe(cmd)
            return o != ""

        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = HotUnplugPciDeviceRsp()
        addr = cmd.pciDeviceAddress

        if not find_pci_device(cmd.vmUuid, addr):
            logger.debug("pci device %s not found" % addr)
            return jsonobject.dumps(rsp)

        domain = hex(0) if len(addr.split(":")) == 2 else hex(int(addr.split(":")[0], 16))
        bus = hex(int(addr.split(":")[-2], 16))
        slot = hex(int(addr.split(":")[-1].split(".")[0], 16))
        function = hex(int(addr.split(":")[-1].split(".")[1], 16))
        content = '''
        <hostdev mode='subsystem' type='pci' managed='yes'>
     <driver name='vfio'/>
     <source>
       <address type='pci' domain='%s' bus='%s' slot='%s' function='%s'/>
     </source>
</hostdev>''' % (domain, bus, slot, function)
        logger.debug("virsh detach xml: %s" % content)
        spath = linux.write_to_temp_file(content)
        r, o, e = bash.bash_roe("virsh detach-device %s %s" % (cmd.vmUuid, spath))
        logger.debug("detach %s to %s finished, %s, %s" % (
            spath, cmd.vmUuid, o, e))
        if r!= 0:
            rsp.success = False
            rsp.error = "%s %s" % (e, o)
        if not linux.wait_callback_success(lambda args: not find_pci_device(args[0], args[1]), [cmd.vmUuid, addr], timeout=20):
            rsp.success = False
            rsp.error = "pci device %s still exists on vm %s after 20s" % (addr, cmd.vmUuid)

        return jsonobject.dumps(rsp)

    def _get_next_usb_port(self, vmUuid, bus):
        conn = libvirt.open('qemu:///system')
        if not conn:
            raise Exception('unable to get libvirt connection')
        dom = conn.lookupByName(vmUuid)
        domain_xml = dom.XMLDesc(0)
        domain_xmlobject = xmlobject.loads(domain_xml)
        # if uhci, port 0 and 1 are hard-coded reserved
        # if ehci/xhci, port 0 is hard-coded reserved
        if bus == 0:
            usb_ports = [0, 1]
        else:
            usb_ports = [0]
        for hostdev in domain_xmlobject.devices.get_child_node_as_list('hostdev'):
            if hostdev.type_ == 'usb':
                for address in hostdev.get_child_node_as_list('address'):
                    if address.type_ == 'usb' and address.bus_ == str(bus):
                        usb_ports.append(int(address.port_))
        conn.close()

        # get the first unused port number
        for i in range(len(usb_ports) + 1):
            if i not in usb_ports:
                return i

    @kvmagent.replyerror
    def kvm_attach_usb_device(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = KvmAttachUsbDeviceRsp()
        bus = int(cmd.usbVersion[0]) - 1
        content = '''
<hostdev mode='subsystem' type='usb' managed='yes'>
  <source>
    <vendor id='0x%s'/>
    <product id='0x%s'/>
    <address bus='%s' device='%s'/>
  </source>
  <address type='usb' bus='%s' port='%s' />
</hostdev>''' % (cmd.idVendor, cmd.idProduct, int(cmd.busNum), int(cmd.devNum), bus, self._get_next_usb_port(cmd.vmUuid, bus))
        spath = linux.write_to_temp_file(content)
        r, o, e = bash.bash_roe("virsh attach-device %s %s" % (cmd.vmUuid, spath))
        logger.debug("attached %s to %s, %s, %s" % (
            spath, cmd.vmUuid, o, e))
        if r!= 0:
            rsp.success = False
            rsp.error = "%s %s" % (e, o)
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def kvm_detach_usb_device(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = KvmDetachUsbDeviceRsp()
        content = '''
<hostdev mode='subsystem' type='usb' managed='yes'>
  <source>
    <vendor id='0x%s'/>
    <product id='0x%s'/>
    <address bus='%s' device='%s'/>
  </source>
</hostdev>''' % (cmd.idVendor, cmd.idProduct, int(cmd.busNum), int(cmd.devNum))
        spath = linux.write_to_temp_file(content)
        r, o, e = bash.bash_roe("virsh detach-device %s %s" % (cmd.vmUuid, spath))
        logger.debug("detached %s from %s, %s, %s" % (
            spath, cmd.vmUuid, o, e))
        if r!= 0:
            rsp.success = False
            rsp.error = "%s %s" % (e, o)
        return jsonobject.dumps(rsp)

    @kvmagent.replyerror
    def kvm_resize_volume(self, req):
        cmd = jsonobject.loads(req[http.REQUEST_BODY])
        rsp = KvmResizeVolumeRsp()

        vm = get_vm_by_uuid(cmd.vmUuid, exception_if_not_existing=False)
        vm.resize_volume(cmd.volume, cmd.deviceType, cmd.size)

        touchQmpSocketWhenExists(cmd.vmUuid)
        return jsonobject.dumps(rsp)

    def start(self):
        http_server = kvmagent.get_http_server()

        http_server.register_async_uri(self.KVM_START_VM_PATH, self.start_vm)
        http_server.register_async_uri(self.KVM_STOP_VM_PATH, self.stop_vm)
        http_server.register_async_uri(self.KVM_PAUSE_VM_PATH, self.pause_vm)
        http_server.register_async_uri(self.KVM_RESUME_VM_PATH, self.resume_vm)
        http_server.register_async_uri(self.KVM_REBOOT_VM_PATH, self.reboot_vm)
        http_server.register_async_uri(self.KVM_DESTROY_VM_PATH, self.destroy_vm)
        http_server.register_async_uri(self.KVM_GET_CONSOLE_PORT_PATH, self.get_console_port)
        http_server.register_async_uri(self.KVM_ONLINE_CHANGE_CPUMEM_PATH, self.online_change_cpumem)
        http_server.register_async_uri(self.KVM_ONLINE_INCREASE_CPU_PATH, self.online_increase_cpu)
        http_server.register_async_uri(self.KVM_ONLINE_INCREASE_MEMORY_PATH, self.online_increase_mem)
        http_server.register_async_uri(self.KVM_VM_SYNC_PATH, self.vm_sync)
        http_server.register_async_uri(self.KVM_ATTACH_VOLUME, self.attach_data_volume)
        http_server.register_async_uri(self.KVM_DETACH_VOLUME, self.detach_data_volume)
        http_server.register_async_uri(self.KVM_ATTACH_ISO_PATH, self.attach_iso)
        http_server.register_async_uri(self.KVM_DETACH_ISO_PATH, self.detach_iso)
        http_server.register_async_uri(self.KVM_MIGRATE_VM_PATH, self.migrate_vm)
        http_server.register_async_uri(self.KVM_TAKE_VOLUME_SNAPSHOT_PATH, self.take_volume_snapshot)
        http_server.register_async_uri(self.KVM_TAKE_VOLUME_BACKUP_PATH, self.take_volume_backup)
        http_server.register_async_uri(self.KVM_TAKE_VOLUMES_SNAPSHOT_PATH, self.take_volumes_snapshots)
        http_server.register_async_uri(self.KVM_TAKE_VOLUMES_BACKUP_PATH, self.take_volumes_backups)
        http_server.register_async_uri(self.KVM_CANCEL_VOLUME_BACKUP_JOBS_PATH, self.cancel_backup_jobs)
        http_server.register_async_uri(self.KVM_BLOCK_STREAM_VOLUME_PATH, self.block_stream)
        http_server.register_async_uri(self.KVM_MERGE_SNAPSHOT_PATH, self.merge_snapshot_to_volume)
        http_server.register_async_uri(self.KVM_LOGOUT_ISCSI_TARGET_PATH, self.logout_iscsi_target)
        http_server.register_async_uri(self.KVM_LOGIN_ISCSI_TARGET_PATH, self.login_iscsi_target)
        http_server.register_async_uri(self.KVM_ATTACH_NIC_PATH, self.attach_nic)
        http_server.register_async_uri(self.KVM_DETACH_NIC_PATH, self.detach_nic)
        http_server.register_async_uri(self.KVM_UPDATE_NIC_PATH, self.update_nic)
        http_server.register_async_uri(self.KVM_CREATE_SECRET, self.create_ceph_secret_key)
        http_server.register_async_uri(self.KVM_VM_CHECK_STATE, self.check_vm_state)
        http_server.register_async_uri(self.KVM_VM_CHANGE_PASSWORD_PATH, self.change_vm_password)
        http_server.register_async_uri(self.KVM_SET_VOLUME_BANDWIDTH, self.set_volume_bandwidth)
        http_server.register_async_uri(self.KVM_DELETE_VOLUME_BANDWIDTH, self.delete_volume_bandwidth)
        http_server.register_async_uri(self.KVM_GET_VOLUME_BANDWIDTH, self.get_volume_bandwidth)
        http_server.register_async_uri(self.KVM_SET_NIC_QOS, self.set_nic_qos)
        http_server.register_async_uri(self.KVM_GET_NIC_QOS, self.get_nic_qos)
        http_server.register_async_uri(self.KVM_HARDEN_CONSOLE_PATH, self.harden_console)
        http_server.register_async_uri(self.KVM_DELETE_CONSOLE_FIREWALL_PATH, self.delete_console_firewall_rule)
        http_server.register_async_uri(self.GET_PCI_DEVICES, self.get_pci_info)
        http_server.register_async_uri(self.HOT_PLUG_PCI_DEVICE, self.hot_plug_pci_device)
        http_server.register_async_uri(self.HOT_UNPLUG_PCI_DEVICE, self.hot_unplug_pci_device)
        http_server.register_async_uri(self.KVM_ATTACH_USB_DEVICE_PATH, self.kvm_attach_usb_device)
        http_server.register_async_uri(self.KVM_DETACH_USB_DEVICE_PATH, self.kvm_detach_usb_device)
        http_server.register_async_uri(self.CHECK_MOUNT_DOMAIN_PATH, self.check_mount_domain)
        http_server.register_async_uri(self.KVM_RESIZE_VOLUME_PATH, self.kvm_resize_volume)

        self.register_libvirt_event()

        self.enable_auto_extend = True
        self.auto_extend_size = 1073741824 * 2

        # the virtio-channel directory used by VR.
        # libvirt won't create this directory when migrating a VR,
        # we have to do this otherwise VR migration may fail
        shell.call('mkdir -p /var/lib/zstack/kvm/agentSocket/')

        @thread.AsyncThread
        def wait_end_signal():
            while True:
                try:
                    self.queue.get(True)

                    while http.AsyncUirHandler.HANDLER_COUNTER.get() != 0:
                        time.sleep(0.1)

                    # the libvirt has been stopped or restarted
                    # to prevent fd leak caused by broken libvirt connection
                    # we have to ask mgmt server to reboot the agent
                    url = self.config.get(kvmagent.SEND_COMMAND_URL)
                    if not url:
                        logger.warn('cannot find SEND_COMMAND_URL, unable to ask the mgmt server to reconnect us')
                        os._exit(1)

                    host_uuid = self.config.get(kvmagent.HOST_UUID)
                    if not host_uuid:
                        logger.warn('cannot find HOST_UUID, unable to ask the mgmt server to reconnect us')
                        os._exit(1)

                    logger.warn("libvirt has been rebooted or stopped, ask the mgmt server to reconnt us")
                    cmd = ReconnectMeCmd()
                    cmd.hostUuid = host_uuid
                    cmd.reason = "libvirt rebooted or stopped"
                    http.json_dump_post(url, cmd, {'commandpath': '/kvm/reconnectme'})
                    os._exit(1)
                except:
                    content = traceback.format_exc()
                    logger.warn(content)

        wait_end_signal()

        @thread.AsyncThread
        def monitor_libvirt():
            while True:
                pid = linux.get_libvirtd_pid()
                if not linux.process_exists(pid):
                    logger.warn(
                        "cannot find the libvirt process, assume it's dead, ask the mgmt server to reconnect us")
                    _stop_world()

                time.sleep(20)

        monitor_libvirt()

        @thread.AsyncThread
        def clean_stale_vm_vnc_port_chain():
            while True:
                logger.debug("do clean up stale vnc port iptable chains")
                cleanup_stale_vnc_iptable_chains()
                time.sleep(600)

        clean_stale_vm_vnc_port_chain()

    def _vm_lifecycle_event(self, conn, dom, event, detail, opaque):
        try:
            evstr = LibvirtEventManager.event_to_string(event)
            vm_uuid = dom.name()
            if evstr not in (LibvirtEventManager.EVENT_STARTED, LibvirtEventManager.EVENT_STOPPED):
                logger.debug("ignore event[%s] of the vm[uuid:%s]" % (evstr, vm_uuid))
                return
            if vm_uuid.startswith("guestfs-"):
                logger.debug("[vm_lifecycle]ignore the temp vm[%s] while using guestfish" % vm_uuid)
                return

            vm_op_judger = self._get_operation(vm_uuid)
            if vm_op_judger and evstr in vm_op_judger.ignore_libvirt_events():
                # this is an operation originated from ZStack itself
                logger.debug(
                    'ignore event[%s] for the vm[uuid:%s], this operation is from ZStack itself' % (evstr, vm_uuid))

                if vm_op_judger.remove_expected_event(evstr) == 0:
                    self._remove_operation(vm_uuid)
                    logger.debug(
                        'events happened of the vm[uuid:%s] meet the expectation, delete the operation judger' % vm_uuid)

                return

            # this is an operation outside zstack, report it
            url = self.config.get(kvmagent.SEND_COMMAND_URL)
            if not url:
                logger.warn('cannot find SEND_COMMAND_URL, unable to report abnormal operation[vm:%s, op:%s]' % (
                    vm_uuid, evstr))
                return

            host_uuid = self.config.get(kvmagent.HOST_UUID)
            if not host_uuid:
                logger.warn(
                    'cannot find HOST_UUID, unable to report abnormal operation[vm:%s, op:%s]' % (vm_uuid, evstr))
                return

            @thread.AsyncThread
            def report_to_management_node():
                cmd = ReportVmStateCmd()
                cmd.vmUuid = vm_uuid
                cmd.hostUuid = host_uuid
                if evstr == LibvirtEventManager.EVENT_STARTED:
                    cmd.vmState = Vm.VM_STATE_RUNNING
                elif evstr == LibvirtEventManager.EVENT_STOPPED:
                    cmd.vmState = Vm.VM_STATE_SHUTDOWN

                logger.debug(
                    'detected an abnormal vm operation[uuid:%s, op:%s], report it to %s' % (vm_uuid, evstr, url))
                http.json_dump_post(url, cmd, {'commandpath': '/kvm/reportvmstate'})

            report_to_management_node()
        except:
            content = traceback.format_exc()
            logger.warn(content)

    # WARNING: it contains quite a few hacks to avoid xmlobject#loads()
    def _vm_reboot_event(self, conn, dom, opaque):
        try:
            domain_xml = dom.XMLDesc(0)
            vm_uuid = dom.name()

            match = re.search(r"""<boot\s+dev='""", domain_xml)
            lindex = 0 if match is None else match.end()
            rindex = domain_xml[lindex:].index("'")
            if lindex == 0 or domain_xml[lindex:lindex+rindex] != 'cdrom':
                logger.debug("the vm[uuid:%s]'s boot device is %s, nothing to do, skip this reboot event" % (
                    vm_uuid, domain_xml[lindex:lindex+rindex]))
                return

            logger.debug(
                'the vm[uuid:%s] is set to boot from the cdrom, for the policy[bootFromHardDisk], the reboot will'
                ' boot from hdd' % vm_uuid)

            self._record_operation(vm_uuid, VmPlugin.VM_OP_REBOOT)

            try: dom.destroy()
            except: pass

            domain_xml = domain_xml[:lindex] + 'hd' + domain_xml[lindex+rindex:]
            xml = re.sub(r"""\stray\s*=\s*'open'""", """ tray='closed'""", domain_xml)
            domain = conn.defineXML(xml)
            domain.createWithFlags(0)
        except:
            content = traceback.format_exc()
            logger.warn(content)

    @bash.in_bash
    @misc.ignoreerror
    def _extend_sharedblock(self, conn, dom, event, detail, opaque):
        logger.debug("extend sharedblock got event from libvirt, %s %s %s %s" %
                     (dom.name(), type(dom), LibvirtEventManager.event_to_string(event), LibvirtEventManager.suspend_event_to_string(detail)))

        if not self.enable_auto_extend:
            return

        def check_lv(file, vm, device):
            virtual_size, image_offest, _ = vm.domain.blockInfo(device)
            lv_size = int(lvm.get_lv_size(file))
            # image_offest = int(bash.bash_o("qemu-img check %s | grep 'Image end offset' | awk -F ': ' '{print $2}'" % file).strip())
            # virtual_size = int(linux.qcow2_virtualsize(file))
            return int(lv_size) < int(virtual_size), image_offest, lv_size, virtual_size

        def extend_lv(event, path, vm, device):
            r, image_offest, lv_size, virtual_size = check_lv(path, vm, device)
            logger.debug("lv %s image offest: %s, lv size: %s, virtual size: %s" %
                         (path, image_offest, lv_size, virtual_size))
            if not r:
                logger.debug("lv %s skip to extend for event %s" % (path, event))
                return

            extend_size = lv_size + self.auto_extend_size if virtual_size > lv_size + self.auto_extend_size else virtual_size
            try:
                lvm.resize_lv(path, extend_size)
            except Exception as e:
                logger.warn("extend lv[%s] to size[%s] failed" % (path, extend_size))
            logger.debug("lv %s extend to %s success" % (path, extend_size))

        def get_path_by_device(device_name, vm):
            for dev in vm.domain_xmlobject.devices.disk:
                if dev.get_child_node("target").dev_ == device_name:
                    return dev.get_child_node("source").file_

        @thread.AsyncThread
        @lock.lock("sharedblock-extend-vm-%s" % dom.name())
        def handle_event(dom, event):
            disk_errors = dom.diskErrors()  # type: dict
            vm_uuid = dom.name()
            fixed = False
            vm = get_vm_by_uuid_no_retry(dom.name(), False)

            if len(disk_errors) == 0:
                logger.debug("no error in vm %s. skip to check and extend volume" % vm_uuid)
                return

            try:
                for device, error in disk_errors.viewitems():
                    if error == libvirt.VIR_DOMAIN_DISK_ERROR_NO_SPACE:
                        fixed = True
                        logger.debug("disk %s of vm %s got ENOSPC" % (device, dom.name()))
                        path = get_path_by_device(device, vm)
                        if not lvm.lv_exists(path):
                            logger.debug("it is not a lvm volume %s, skip to extend" % path)
                            continue
                        extend_lv(event, path, vm, device)
            except Exception as e:
                logger.warn("got excetion: %s" % e)

            if fixed is True:
                vm.resume()
                touchQmpSocketWhenExists(vm_uuid)

        event = LibvirtEventManager.event_to_string(event)
        if event not in (LibvirtEventManager.EVENT_SUSPENDED,):
            return
        handle_event(dom, event)

    @bash.in_bash
    def _release_sharedblocks(self, conn, dom, event, detail, opaque):
        logger.debug("release sharedblock got event from libvirt, %s %s" % (dom.name(), LibvirtEventManager.event_to_string(event)))

        @linux.retry(times=5, sleep_time=1)
        def wait_volume_unused(volume):
            used_process = linux.linux_lsof(volume)
            if len(used_process) != 0:
                raise RetryException("volume %s still used: %s" % (volume, used_process))

        @thread.AsyncThread
        def deactivate_volume(event, file, vm_uuid):
            volume = file.strip().split("'")[1]
            try:
                wait_volume_unused(volume)
            finally:
                used_process = linux.linux_lsof(volume)
            if len(used_process) == 0:
                try:
                    lvm.deactive_lv(volume, False)
                    logger.debug(
                        "deactivated volume %s for event %s happend on vm %s success" % (volume, event, vm_uuid))
                except Exception as e:
                    logger.debug("deactivate volume %s for event %s happend on vm %s failed, %s" % (
                        volume, event, vm_uuid, e.message))
                    content = traceback.format_exc()
                    logger.warn("traceback: %s" % content)
            else:
                logger.debug("volume %s still used: %s, skip to deactivate" % (volume, used_process))

        try:
            event = LibvirtEventManager.event_to_string(event)
            if event not in (LibvirtEventManager.EVENT_SHUTDOWN,):
                return

            vm_uuid = dom.name()
            out = bash.bash_o("virsh dumpxml %s | grep \"source file='/dev/\"" % vm_uuid).strip().splitlines()
            if len(out) != 0:
                for file in out:
                    deactivate_volume(event, file, vm_uuid)
        except:
            content = traceback.format_exc()
            logger.warn("traceback: %s" % content)

    def _set_vnc_port_iptable_rule(self, conn, dom, event, detail, opaque):
        try:
            event = LibvirtEventManager.event_to_string(event)
            if event not in (LibvirtEventManager.EVENT_STARTED, LibvirtEventManager.EVENT_STOPPED):
                return
            vm_uuid = dom.name()
            if vm_uuid.startswith("guestfs-"):
                logger.debug("[set_vnc_port_iptable]ignore the temp vm[%s] while using guestfish" % vm_uuid)
                return

            domain_xml = dom.XMLDesc(0)
            domain_xmlobject = xmlobject.loads(domain_xml)

            if is_namespace_used():
                internal_id_node = find_zstack_metadata_node(etree.fromstring(domain_xml), 'internalId')
                vm_id = internal_id_node.text if internal_id_node is not None else None
            else:
                vm_id = domain_xmlobject.metadata.internalId.text_ if xmlobject.has_element(domain_xmlobject, 'metadata.internalId') else None

            if not vm_id:
                logger.debug('vm[uuid:%s] is not managed by zstack,  do not configure the vnc iptables rules' % vm_uuid)
                return

            vir = VncPortIptableRule()
            if LibvirtEventManager.EVENT_STARTED == event:

                if is_namespace_used():
                    host_ip_node = find_zstack_metadata_node(etree.fromstring(domain_xml), 'hostManagementIp')
                    vir.host_ip = host_ip_node.text
                else:
                    vir.host_ip = domain_xmlobject.metadata.hostManagementIp.text_

                if shell.run('ip addr | grep -w %s > /dev/null' % vir.host_ip) != 0:
                    logger.debug('the vm is migrated from another host, we do not need to set the console firewall, as '
                                 'the management node will take care')
                    return
                for g in domain_xmlobject.devices.get_child_node_as_list('graphics'):
                    if g.type_ == 'vnc' or g.type_ == 'spice':
                        vir.port = g.port_
                        break

                vir.vm_internal_id = vm_id
                vir.apply()
                logger.debug('Enable [port:%s] in firewall rule for vm[uuid:%s] console' % (vir.port, vm_id))
            elif LibvirtEventManager.EVENT_STOPPED == event:
                vir.vm_internal_id = vm_id
                vir.delete()
                logger.debug('Delete firewall rule for vm[uuid:%s] console' % vm_id)

        except:
            # if vm do live migrate the dom may not be found or the vm has been undefined
            vm = get_vm_by_uuid(dom.name(), False)
            if not vm:
                logger.debug("can not get domain xml of vm[uuid:%s], "
                             "the vm may be just migrated here or it has already been undefined" % dom.name())
                return

            content = traceback.format_exc()
            logger.warn(content)

    def register_libvirt_event(self):
        #LibvirtAutoReconnect.add_libvirt_callback(libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, self._vm_lifecycle_event)
        LibvirtAutoReconnect.add_libvirt_callback(libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE,
                                                  self._set_vnc_port_iptable_rule)
        LibvirtAutoReconnect.add_libvirt_callback(libvirt.VIR_DOMAIN_EVENT_ID_REBOOT, self._vm_reboot_event)
        LibvirtAutoReconnect.add_libvirt_callback(libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, self._release_sharedblocks)
        LibvirtAutoReconnect.add_libvirt_callback(libvirt.VIR_DOMAIN_EVENT_ID_LIFECYCLE, self._extend_sharedblock)
        LibvirtAutoReconnect.register_libvirt_callbacks()

    def stop(self):
        pass

    def configure(self, config):
        self.config = config


class EmptyCdromConfig():
    def __init__(self, targetDev, bus, unit):
        self.targetDev = targetDev
        self.bus = bus
        self.unit = unit


class VolumeSnapshotJobStruct(object):
    def __init__(self, volumeUuid, volume, installPath, vmInstanceUuid, previousInstallPath,
                 newVolumeInstallPath, live=True, full=False):
        self.volumeUuid = volumeUuid
        self.volume = volume
        self.installPath = installPath
        self.vmInstanceUuid = vmInstanceUuid
        self.previousInstallPath = previousInstallPath
        self.newVolumeInstallPath = newVolumeInstallPath
        self.live = live
        self.full = full


class VolumeSnapshotResultStruct(object):
    def __init__(self, volumeUuid, previousInstallPath, installPath, size=None):
        """

        :type volumeUuid: str
        :type size: long
        :type installPath: str
        :type previousInstallPath: str
        """
        self.volumeUuid = volumeUuid
        self.previousInstallPath = previousInstallPath
        self.installPath = installPath
        self.size = size


@bash.in_bash
@misc.ignoreerror
def touchQmpSocketWhenExists(vmUuid):
    if vmUuid is None:
        return
    path = "%s/%s.sock" % (QMP_SOCKET_PATH, vmUuid)
    if os.path.exists(path):
        bash.bash_roe("touch %s" % path)
