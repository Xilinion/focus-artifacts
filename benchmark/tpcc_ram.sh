#!/usr/bin/bash -x

SYSTEMS=(2pl-no-wait occ-serial sto-disk sto-memory sto-sketch sto-counter-lazy tictoc-disk tictoc-memory tictoc-sketch tictoc-counter-lazy tictoc-disk-cache sto-disk-cache)
WORKLOADS=(tpcc-wh4 tpcc-wh8 tpcc-wh16 tpcc-wh32)

LOG_DIR=/proj/tasrdma-PG0/deukyeon/extended_ram0/tpcc
OUTPUT_DIR=$LOG_DIR

DEV=/dev/ram0

NRUNS=3

CACHE_SIZE=256
RUN_SEC=120

mkdir -p $LOG_DIR

for work in ${WORKLOADS[@]}
do
    for sys in ${SYSTEMS[@]}
    do
        for thr in 120
        do
            for run in $(seq 1 ${NRUNS})
            do
                LOG_FILE="$LOG_DIR/${sys}_${work}_${thr}_${run}.log"

                # Skip if log file already exists and contains the desired line
                if [ -f "$LOG_FILE" ] && grep -q "# Transaction throughput (KTPS)" "$LOG_FILE"; then
                    continue
                fi

                # Retry until the output file contains the desired line
                while true
                do
                    #sudo blkdiscard $DEV
		    sudo modprobe brd rd_nr=1 rd_size=$((120 * 1024 * 1024))
                    python3 ./tpcc.py -s "$sys" -w "$work" -t "$thr" -c "$CACHE_SIZE" -r "$RUN_SEC" -d "$DEV" | tee "$LOG_FILE"
		    sudo modprobe -r brd

                    # Check if the log file contains the required line
                    if grep -q "# Transaction throughput (KTPS)" "$LOG_FILE"; then
                        break
                    fi
                done
            done
        done
    done
done

mkdir -p $OUTPUT_DIR
python3 parse.py $LOG_DIR $OUTPUT_DIR
