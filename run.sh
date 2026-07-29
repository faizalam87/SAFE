#!/bin/bash

TRACES_DIR=${TRACES_DIR:-./trace}
OUT=temp_output
BIN=./bin
WARM=5000000
SIM=200000000

# Keep exactly 14 benchmarks active here to get 1001 combinations
BENCHES=(
  602.gcc_s-734B.trace.xz
  605.mcf_s-472.trace.xz
  605.mcf_s-484B.trace.xz
#  605.mcf_s-665B.trace.xz
  #605.mcf_s-782B.trace.xz
#  605.mcf_s-994B.trace.xz
  623.xalancbmk_s-10B.trace.xz
 # 623.xalancbmk_s-165B.trace.xz
 # 623.xalancbmk_s-202B.trace.xz
  623.xalancbmk_s-325B.trace.xz
#  623.xalancbmk_s-592B.trace.xz
#  623.xalancbmk_s-700B.trace.xz
#  625.x264_s-12B.trace.xz
  625.x264_s-18B.trace.xz
#  625.x264_s-20B.trace.xz
#  625.x264_s-33B.trace.xz
#  625.x264_s-39B.trace.xz
#  628.pop2_s_17B.trace.xz
#  641.leela_s-149B.trace.xz
#  648.exchange2_s-72B.trace.xz
#  649.fotonik3d_s-1B.trace.xz
  657.xz_s-56B.trace.xz
  654.roms_s_294B.trace.xz
#  654.roms_s_293B.trace.xz
#  654.roms_s_523B.trace.xz
)

job_count=0
MAX_CONCURRENT_JOBS=8 

NUM_BENCHES=${#BENCHES[@]}

# 4-level nested loop to create combinations (N choose 4)
for ((i=0; i<NUM_BENCHES-3; i++)); do
  for ((j=i+1; j<NUM_BENCHES-2; j++)); do
    for ((k=j+1; k<NUM_BENCHES-1; k++)); do
      for ((l=k+1; l<NUM_BENCHES; l++)); do
      
        # Get the 4 distinct trace files
        b1="${BENCHES[$i]}"
        b2="${BENCHES[$j]}"
        b3="${BENCHES[$k]}"
        b4="${BENCHES[$l]}"
        
        t1="$TRACES_DIR/$b1"
        t2="$TRACES_DIR/$b2"
        t3="$TRACES_DIR/$b3"
        t4="$TRACES_DIR/$b4"
        
        # Create a unique name for this mix to use as the output file
        # We strip .trace.xz for cleaner naming
        mix_name="${b1%.trace.xz}_${b2%.trace.xz}_${b3%.trace.xz}_${b4%.trace.xz}"

        for var in ip_guard ip_noguard no_prefetch; do
          mkdir -p "$OUT/$var/$mix_name"
          
          # Pass the 4 distinct traces to ChampSim
          "$BIN/$var" -warmup_instructions "$WARM" -simulation_instructions "$SIM" -traces "$t1" "$t2" "$t3" "$t4" \
            > "$OUT/$var/$mix_name/$mix_name.txt" 2>&1 &
            
          ((job_count++))
          if [[ $job_count -ge $MAX_CONCURRENT_JOBS ]]; then
            wait -n
            ((job_count--))
          fi
        done

      done
    done
  done
done

wait
echo "All 1001 multi-core simulations completed!"