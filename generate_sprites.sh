#!/bin/bash

BIN=".venv/bin/mflux-generate-flux2"
OUT_DIR="ttm-game/public/assets/vehicles"

declare -a VEHICLES=(
  "0:Steam Locomotive:#8b4513"
  "1:Diesel Locomotive:#228b22"
  "2:Electric Locomotive:#4169e1"
  "3:High Speed Train:#dc143c"
  "4:Passenger Car:#228b22"
  "5:Cargo Wagon:#8b4513"
  "6:Minibus:#ff6347"
  "7:Bus:#228b22"
  "8:Coach:#4169e1"
  "9:Cargo Truck:#8b4513"
  "10:Long Distance Truck:#b8860b"
  "11:Mail Van:#ffff00"
  "12:Cessna:#ffffff"
  "13:DC-3:#c0c0c0"
  "14:Boeing 707:#4169e1"
  "15:Cargo Plane:#8b4513"
  "16:Air Mail Plane:#ffff00"
  "17:Cargo Ship:#8b4513"
  "18:Passenger Ship:#228b22"
  "19:Ferry:#4169e1"
)

for entry in "${VEHICLES[@]}"; do
  IFS=':' read -r vid name color <<< "$entry"
  prompt="Strict 3/4 isometric view of a $name, primary color $color, Transport Tycoon game sprite style, clean vector art, white background, centered, no text, no shadows"
  output="$OUT_DIR/v${vid}.png"
  
  echo "Generating $name..."
  $BIN --model flux2-klein-4b --prompt "$prompt" --output "$output" --steps 4 -q 8 --seed $((vid * 1234)) 2>&1
  if [ $? -eq 0 ]; then
    echo "  OK: $output"
  else
    echo "  ERROR generating $name"
  fi
done
