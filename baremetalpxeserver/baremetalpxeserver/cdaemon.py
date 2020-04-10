'''

@author: frank
'''
import sys, os, os.path
from zstacklib.utils import log
from zstacklib.utils import linux
import zstacklib.utils.iptables as iptables

pidfile = '/var/run/zstack/zstack-baremetalpxeserver.pid'
log.configure_log('/var/log/zstack/zstack-baremetalpxeserver.log')
logger = log.get_logger(__name__)
import pxeserveragent

def prepare_pid_dir(path):
    pdir = os.path.dirname(path)
    if not os.path.isdir(pdir):
        os.makedirs(pdir)

def main():
    usage = 'usage: python -c "from baremetalpxeserver import cdaemon; cdaemon.main()" start|stop|restart'
    if len(sys.argv) != 2 or not sys.argv[1] in ['start', 'stop', 'restart']:
        print usage
        sys.exit(1)

    global pidfile
    prepare_pid_dir(pidfile)

    try:
        cmd = sys.argv[1]
        py_process_name = 'from baremetalpxeserver import cdaemon'
        agentdaemon = pxeserveragent.PxeServerDaemon(pidfile, py_process_name)
        if cmd == 'start':
            logger.debug('zstack-baremetalpxeserver starts')
            agentdaemon.start()
        elif cmd == 'stop':
            logger.debug('zstack-baremetalpxeserver stops')
            agentdaemon.stop()
        elif cmd == 'restart':
            logger.debug('zstack-baremetalpxeserver restarts')
            agentdaemon.restart()
        sys.exit(0)
    except Exception:
        logger.warning(linux.get_exception_stacktrace())
        sys.exit(1)

if __name__ == '__main__':
    main()
