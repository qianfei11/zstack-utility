import shutil
import os

black_dpath_list = ["", "/", "*", "/root", "/var", "/bin", "/lib", "/sys"]


def rm_dir_force(dpath, only_check=False):
    if dpath.strip() in black_dpath_list:
        raise Exception("how dare you delete directory %s" % dpath)
    if os.path.exists(dpath) and not only_check:
        if os.path.isdir(dpath):
            shutil.rmtree(dpath)
        else:
            rm_file_force(dpath)
    else:
        return dpath


def rm_file_force(fpath):
    try:
        os.remove(fpath)
    except:
        pass

import ctypes
libc = ctypes.CDLL("libc.so.6")

def sync_file(fpath):
    if not os.path.isfile(fpath):
        return

    fd = os.open(fpath, os.O_RDONLY|os.O_NONBLOCK)
    try:
        libc.syncfs(fd)
    except:
        pass
    finally:
        os.close(fd)
