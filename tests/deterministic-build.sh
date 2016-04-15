#!/bin/bash
# Repeatedly build system images and check for repeatability of overlapping
# files from different chunks in resulting system builds
# Run from definitions root
# Usage: sudo check-repeatability <system name> <architecture> [run count]

SYSTEM=$1
SYS_NAME=$(echo $SYSTEM | cut -d '/' -f 2 | sed 's@\(.*\)\.morph@\1@')
ARCH=$2

# Build
echo "Building $SYSTEM, log at \`tail -f $(pwd)/original-build\`"
../ybd/ybd.py $1 $2 | tee original-build 2>&1 > /dev/null

# 16-04-15 00:00:00 [SETUP] /src/cache/artifacts is directory for artifacts
# 16-04-15 00:00:08 [0/28/125] [base-system-x86_64-generic] WARNING: overlapping path /sbin/halt
# 16-04-15 00:00:38 [1/28/125] [base-system-x86_64-generic] Cached 1504286720 bytes d0783c3f0bb26c630f85c33fac06766f as base-system-x86_64-generic.e94e0734c094baced9f5af1909b56e5b86dc4ff4700827b2762007edfd6223eb

ARTIFACT_DIR=$(awk '/is directory for artifacts/ {print $4}' original-build)
SYS_ARTIFACT=$(awk "/.*Cached.*$SYS_NAME.*/ {print \$NF}" original-build)

if [ "$SYS_ARTIFACT" == "" ]; then
	echo "No system artifact found. You may need to clear the YBD cache directory to rebuild."
	exit 1
fi

OVERLAPS=$(awk '/WARNING: overlapping path/ {print $NF}' original-build)

SYS_ARTIFACT_PATH="$ARTIFACT_DIR/$SYS_ARTIFACT"
SYS_UNPACKED="$SYS_ARTIFACT_PATH/$SYS_ARTIFACT.unpacked"

echo -n > original-md5sums
for o in $OVERLAPS; do
	FILE=$(file "$SYS_UNPACKED$o" | awk '/broken symbolic link/ {print $NF}')
	if [ "$FILE" == ""  ]; then
		md5sum "$SYS_UNPACKED$o" >> original-md5sums
	else
		echo "Following symbolic link $o -> $FILE"
		md5sum "$SYS_UNPACKED$FILE" >> original-md5sums
	fi
done

# Run tests:
COUNT=0
while true; do

	# Delete system artifact
	rm -rf $SYS_ARTIFACT_PATH

	# Rebuild
	echo "Building $SYSTEM, log at \`tail -f $(pwd)/build-$COUNT\`"
	../ybd/ybd.py $1 $2 | tee "build-$COUNT" 2>&1 > /dev/null

	# Status
	if md5sum -c original-md5sums &> /dev/null; then
		echo "Run $COUNT succeeded"
	else
		echo "Run $COUNT failed"
	fi
	COUNT=$(($COUNT+1))

done
