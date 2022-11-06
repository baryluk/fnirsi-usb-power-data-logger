#!/usr/bin/env -S gnuplot -c

if (ARGC >= 1) {
  f = ARG1
} else {
  f = "live.txt"
}

LIVE = 0
if (ARGC >= 2) {
  if (ARG2 eq "--live") {
    LIVE = 1
  } else {
    print "Unknown second argument. Only supported --live"
    exit(1)
  }
}

# Interactive
if (LIVE != 0) {
  # set terminal wxt size 1850,1750
  set terminal wxt size 1900,1000
}

f = "<grep -v ^timestamp " . f


while (1) {

if (LIVE == 0) {
# To file
  set terminal pngcairo size 1600,1200 noenhanced
  set output "plot.png"
}

set timefmt "%s"
set format x "%H:%M:%S"  # %Y-%m-%d
set xdata time
set xlabel "Time"


set ylabel "Voltage [V]"
set y2tics
set y2label "Current [A]"

set grid

set multiplot layout 5,1

set yrange [*<2.0:5.2<*]

plot f u 1:3 w steps lw 2 title "Voltage", \
    "" u 1:4 w steps lw 2 axis x1y2 title "Current"


unset y2label
unset y2tics


set ylabel "Energy [Wh]"
# W⋅s == J

set yrange [0:*]

plot f u 1:($8/3600) w steps lw 2 title "Energy"
# 1:9 - capacity in A⋅s == C

set ylabel "Power [W]"
set y2tics
set y2label "ESR [Ohm]"

set yrange [0.0:]
set y2range [0.0:*<100]

plot f u 1:($3*$4) w steps lw 2 title "Power", \
     f u 1:($4 > 0.01 ? $3/$4 : 10000) w steps lw 2 axis x1y2 title "ESR"


unset y2label
unset y2tics

set ylabel "Voltage [V]"
set yrange [0.0:4.0<*]
plot f u 1:5 w steps lw 2 title "D+", "" u 1:6 w steps lw 3 title "D-"

set ylabel "Temperature [degC]"
set yrange [*:*]
plot f u 1:7 every 10 w steps lw 2 title "Temperature"


unset multiplot
unset output

if (LIVE == 0) {
  break
} else {
  pause 10 # for interactive redraw
}

}

set terminal pngcairo size 1600,1600 noenhanced
set output "plot-iv.png"

unset y2label
unset y2tics

set xdata  # revert set xdata time
set format x "%.3f"
set xlabel "Current [A]"

set format y "%.3f"
set ylabel "Voltage [V]"

set xrange [0:]
set yrange [0:]

plot f u 4:3 w steps lw 2 title "V(I)"

unset output
