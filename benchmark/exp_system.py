import os
import time
import subprocess

available_systems = [
    'splinterdb',
    'tictoc-disk',
    'silo-disk',
    'occ-serial',
    'occ-parallel',
    'silo-memory',
    'tictoc-memory',
    'tictoc-counter',
    'tictoc-counter-lazy',
    'tictoc-sketch',
    'tictoc-sketch-lazy',
    'tictoc-disk-cache',
    'sto-disk',
    'sto-disk-cache',
    'sto-sketch',
    'sto-sketch-lazy',
    'sto-counter',
    'sto-counter-lazy',
    'sto-memory',
    'sto-legacy',
    '2pl-no-wait',
    '2pl-wait-die',
    '2pl-wound-wait',
    'mvcc-disk',
    'mvcc-disk-cache',
    'mvcc-memory',
    'mvcc-counter',
    'mvcc-counter-lazy',
    'mvcc-sketch',
    'mvcc-sketch-lazy',
    'tictoc-memory-trace',
    'tictoc-disk-trace',
    'tictoc-memory-ext',
    'tictoc-disk-ext',
]

system_sed_map = {
    'occ-serial': ["sed -i 's/#define EXPERIMENTAL_MODE_KR_OCC [ ]*0/#define EXPERIMENTAL_MODE_KR_OCC 1/g' src/experimental_mode.h"],
    'occ-parallel': ["sed -i 's/#define EXPERIMENTAL_MODE_KR_OCC_PARALLEL [ ]*0/#define EXPERIMENTAL_MODE_KR_OCC_PARALLEL 1/g' src/experimental_mode.h"],
    'silo-memory': ["sed -i 's/#define EXPERIMENTAL_MODE_SILO_MEMORY [ ]*0/#define EXPERIMENTAL_MODE_SILO_MEMORY 1/g' src/experimental_mode.h"],
    'tictoc-disk': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_DISK [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_DISK 1/g' src/experimental_mode.h"],
    'tictoc-memory': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_MEMORY [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_MEMORY 1/g' src/experimental_mode.h"],
    'tictoc-counter': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_COUNTER [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_COUNTER 1/g' src/experimental_mode.h"],
    'tictoc-counter-lazy': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_COUNTER_LAZY [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_COUNTER_LAZY 1/g' src/experimental_mode.h"],
    'tictoc-sketch': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_SKETCH [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_SKETCH 1/g' src/experimental_mode.h"],
    'tictoc-sketch-lazy': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_SKETCH_LAZY [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_SKETCH_LAZY 1/g' src/experimental_mode.h"],
    'tictoc-disk-cache': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_DISK_CACHE [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_DISK_CACHE 1/g' src/experimental_mode.h"],
    'sto-disk': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_DISK [ ]*0/#define EXPERIMENTAL_MODE_STO_DISK 1/g' src/experimental_mode.h"],
    'sto-disk-cache': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_DISK_CACHE [ ]*0/#define EXPERIMENTAL_MODE_STO_DISK_CACHE 1/g' src/experimental_mode.h"],
    'sto-memory': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_MEMORY [ ]*0/#define EXPERIMENTAL_MODE_STO_MEMORY 1/g' src/experimental_mode.h"],
    'sto-sketch': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_SKETCH [ ]*0/#define EXPERIMENTAL_MODE_STO_SKETCH 1/g' src/experimental_mode.h"],
    'sto-sketch-lazy': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_SKETCH_LAZY [ ]*0/#define EXPERIMENTAL_MODE_STO_SKETCH_LAZY 1/g' src/experimental_mode.h"],
    'sto-counter': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_COUNTER [ ]*0/#define EXPERIMENTAL_MODE_STO_COUNTER 1/g' src/experimental_mode.h"],
    'sto-counter-lazy': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_COUNTER_LAZY [ ]*0/#define EXPERIMENTAL_MODE_STO_COUNTER_LAZY 1/g' src/experimental_mode.h"],
    'sto-legacy': ["sed -i 's/#define EXPERIMENTAL_MODE_STO_LEGACY [ ]*0/#define EXPERIMENTAL_MODE_STO_LEGACY 1/g' src/experimental_mode.h"],
    '2pl-no-wait': ["sed -i 's/#define EXPERIMENTAL_MODE_2PL_NO_WAIT [ ]*0/#define EXPERIMENTAL_MODE_2PL_NO_WAIT 1/g' src/experimental_mode.h"],
    '2pl-wait-die': ["sed -i 's/#define EXPERIMENTAL_MODE_2PL_WAIT_DIE [ ]*0/#define EXPERIMENTAL_MODE_2PL_WAIT_DIE 1/g' src/experimental_mode.h"],
    '2pl-wound-wait': ["sed -i 's/#define EXPERIMENTAL_MODE_2PL_WOUND_WAIT [ ]*0/#define EXPERIMENTAL_MODE_2PL_WOUND_WAIT 1/g' src/experimental_mode.h"],
    'mvcc-disk': ["sed -i 's/#define EXPERIMENTAL_MODE_MVCC_DISK [ ]*0/#define EXPERIMENTAL_MODE_MVCC_DISK 1/g' src/experimental_mode.h"],
    'mvcc-disk-cache': ["sed -i 's/#define EXPERIMENTAL_MODE_MVCC_DISK_CACHE [ ]*0/#define EXPERIMENTAL_MODE_MVCC_DISK_CACHE 1/g' src/experimental_mode.h"],
    'mvcc-memory': ["sed -i 's/#define EXPERIMENTAL_MODE_MVCC_MEMORY [ ]*0/#define EXPERIMENTAL_MODE_MVCC_MEMORY 1/g' src/experimental_mode.h"],
    'mvcc-counter': ["sed -i 's/#define EXPERIMENTAL_MODE_MVCC_COUNTER [ ]*0/#define EXPERIMENTAL_MODE_MVCC_COUNTER 1/g' src/experimental_mode.h"],
    'mvcc-counter-lazy': ["sed -i 's/#define EXPERIMENTAL_MODE_MVCC_COUNTER_LAZY [ ]*0/#define EXPERIMENTAL_MODE_MVCC_COUNTER_LAZY 1/g' src/experimental_mode.h"],
    'mvcc-sketch': ["sed -i 's/#define EXPERIMENTAL_MODE_MVCC_SKETCH [ ]*0/#define EXPERIMENTAL_MODE_MVCC_SKETCH 1/g' src/experimental_mode.h"],
    'mvcc-sketch-lazy': ["sed -i 's/#define EXPERIMENTAL_MODE_MVCC_SKETCH_LAZY [ ]*0/#define EXPERIMENTAL_MODE_MVCC_SKETCH_LAZY 1/g' src/experimental_mode.h"],
    'tictoc-memory-trace': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_MEMORY_TRACE [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_MEMORY_TRACE 1/g' src/experimental_mode.h"],
    'tictoc-disk-trace': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_DISK_TRACE [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_DISK_TRACE 1/g' src/experimental_mode.h"],
    'tictoc-memory-ext': ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_MEMORY_EXT [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_MEMORY_EXT 1/g' src/experimental_mode.h"],
    'tictoc-disk-ext':   ["sed -i 's/#define EXPERIMENTAL_MODE_TICTOC_DISK_EXT [ ]*0/#define EXPERIMENTAL_MODE_TICTOC_DISK_EXT 1/g' src/experimental_mode.h"],
}

class ExpSystem:
    @staticmethod
    def build(sys, splinterdb_dir, spl_threads, backup=True):
        spl_threads = max(64, spl_threads)

        def run_cmd(cmd):
            subprocess.call(cmd, shell=True)
        
        def change_max_threads():
            with open('src/platform_linux/platform.h', 'r') as f:
                lines = f.readlines()
            with open('src/platform_linux/platform.h', 'w') as f:
                for line in lines:
                    if line.startswith('#define MAX_THREADS ('):
                        f.write(f'#define MAX_THREADS ({spl_threads})\n')
                    else:
                        f.write(line)

        os.environ['CC'] = 'clang'
        os.environ['LD'] = 'clang'
        os.makedirs('/home/xt253/.tmp', exist_ok=True)
        os.environ['TMPDIR'] = '/home/xt253/.tmp'
        current_dir = os.getcwd()
        if backup:
            run_cmd(f'tar czf splinterdb-backup-{time.time()}.tar.gz {splinterdb_dir}')
        os.chdir(splinterdb_dir)
        run_cmd('git checkout -- src/experimental_mode.h')
        run_cmd('make clean')
        run_cmd('date')
        run_cmd('hostname -A')
        run_cmd('git rev-parse --verify HEAD')
        if sys in system_sed_map:
            for sed in system_sed_map[sys]:
                run_cmd(sed)
        change_max_threads()
        run_cmd('TMPDIR=/home/xt253/.tmp make -j4 INSTALL_PATH=/home/xt253/.local install')
        os.chdir(current_dir)
        run_cmd('make clean')
        run_cmd('make')

    @staticmethod
    def build_for_long_txn(sys, splinterdb_dir, spl_threads, backup=True):
        spl_threads = max(64, spl_threads)

        def run_cmd(cmd):
            subprocess.call(cmd, shell=True)
        
        def change_max_threads():
            with open('src/platform_linux/platform.h', 'r') as f:
                lines = f.readlines()
            with open('src/platform_linux/platform.h', 'w') as f:
                for line in lines:
                    if line.startswith('#define MAX_THREADS ('):
                        f.write(f'#define MAX_THREADS ({spl_threads})\n')
                    else:
                        f.write(line)

        os.environ['CC'] = 'clang'
        os.environ['LD'] = 'clang'
        os.makedirs('/home/xt253/.tmp', exist_ok=True)
        os.environ['TMPDIR'] = '/home/xt253/.tmp'
        current_dir = os.getcwd()
        if backup:
            run_cmd(f'tar czf splinterdb-backup-{time.time()}.tar.gz {splinterdb_dir}')
        os.chdir(splinterdb_dir)
        run_cmd('git checkout -- src/experimental_mode.h')
        run_cmd('make clean')
        run_cmd('date')
        run_cmd('hostname -A')
        run_cmd('git rev-parse --verify HEAD')
        if sys in system_sed_map:
            for sed in system_sed_map[sys]:
                run_cmd(sed)
        change_max_threads()

        filename = 'src/transaction_impl/transaction_kr_occ.h'
        run_cmd(f'git checkout -- {filename}')
        with open(splinterdb_dir + "/" + filename, 'r') as f:
            write_lines = []
            for line in f:
                if line.startswith("#define TRANSACTION_RW_SET_MAX"):
                    write_lines.append("#define TRANSACTION_RW_SET_MAX 1000\n")
                else:
                    write_lines.append(line)
        with open(splinterdb_dir + "/" + filename, 'w') as f:
            f.writelines(write_lines)
        
        for filename in ['transaction_sto.h', 'transaction_tictoc_sketch.h', 'transaction_mvcc_sketch.h', 'transaction_tictoc_disk_cache.h', 'transaction_sto_disk_cache.h', 'transaction_mvcc_disk_cache.h']:
            filename = f'src/transaction_impl/{filename}'
            run_cmd(f'git checkout -- {filename}')
            with open(splinterdb_dir + "/" + filename, 'r') as f:
                write_lines = []
                for line in f:
                    if "const int num_active_keys_per_txn =" in line:
                        write_lines.append("const int num_active_keys_per_txn = 1000;\n")
                    else:
                        write_lines.append(line)
            with open(splinterdb_dir + "/" + filename, 'w') as f:
                f.writelines(write_lines)

        run_cmd('make -j4 INSTALL_PATH=/home/xt253/.local install')
        os.chdir(current_dir)
        run_cmd('make clean')
        run_cmd('make')
