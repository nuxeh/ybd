#!/bin/bash
# Repeatedly build system images and check for repeatability of overlapping
# files from different chunks in resulting system builds. This 
# Run from definitions root
# Usage: sudo check-repeatability <system name> <architecture> [run count]

OF="build-results-$(date | sed 's/\s/-/g;s/:/-/g')" # Output file for results
echo "Results piped to $(pwd)/$OF"
THOROUGH=1
LINKS=1

function report() {
	(
	echo 'Generating report...'
	FC=$(grep 'Run.*failed' "$OF" | wc -l)
	SC=$(grep 'Run.*succeeded' "$OF" | wc -l)
	echo "$FC tests failed"	
	echo "$SC tests succeeded"
	if which bc > /dev/null; then echo $(echo "scale=2; $SC*100/$FC" | bc) percent passed.; fi
	) >> $OF
}

trap report EXIT

SYSTEM=$1
SYS_NAME=$(echo $SYSTEM | cut -d '/' -f 2 | sed 's@\(.*\)\.morph@\1@')
ARCH=$2

# Build
echo "Building $SYSTEM, log at \`tail -f $(pwd)/original-build\`"
../ybd/ybd.py $1 $2 | tee original-build 2>&1 > /dev/null

# 16-04-15 00:00:00 [SETUP] /src/cache/artifacts is directory for artifacts
# 16-04-15 00:00:08 [0/28/125] [base-system-x86_64-generic] WARNING: overlapping path /sbin/halt
# 16-04-15 00:00:38 [1/28/125] [base-system-x86_64-generic] Cached 1504286720 bytes d0783c3f0bb26c630f85c33fac06766f as base-system-x86_64-generic.e94e0734c094baced9f5af1909b56e5b86dc4ff4700827b2762007edfd6223eb

ARTIFACT_DIR=$(sed 's/^[[:digit:]]*//' original-build | awk '/is directory for artifacts/ {print $4}')
SYS_ARTIFACT=$(awk "/.*Cached.*$SYS_NAME.*/ {print \$NF}" original-build)

if [ "$SYS_ARTIFACT" == "" ]; then
	echo "No system artifact found. You may need to clear the YBD cache directory to rebuild."
	exit 1
fi

OVERLAPS=$(awk '/WARNING: overlapping path/ {print $NF}' original-build)

SYS_ARTIFACT_PATH="$ARTIFACT_DIR/$SYS_ARTIFACT"
SYS_UNPACKED="$SYS_ARTIFACT_PATH/$SYS_ARTIFACT.unpacked"

echo "Overlapping files:"
echo -n > original-md5sums
for o in $OVERLAPS; do
	echo "$o"
	FILE=$(file "$SYS_UNPACKED$o" | awk '/broken symbolic link/ {print $NF}')
	if [ "$FILE" == ""  ]; then
		md5sum "$SYS_UNPACKED$o" >> original-md5sums
	else
		echo "Following symbolic link $o -> $FILE"
		md5sum "$SYS_UNPACKED$FILE" >> original-md5sums
	fi
done

echo -n > original-md5sums-all-reg-files
if [ $THOROUGH -eq 1 ]; then
	# Checksum all files
	echo "Generating checksums for all regular files..."
	# Not ldconfig cache
	find "$SYS_UNPACKED" -type f -exec md5sum "{}" + > original-md5sums-all-reg-files #2> /dev/null
	echo "Evaluated $(wc -l original-md5sums-all-reg-files | awk '{print $1}') files."
fi

echo -n > original-links
if [ $LINKS -eq 1 ]; then
	echo "Finding symbolic links..."
	find "$SYS_UNPACKED" -exec file "{}" + | grep 'symbolic link to' > original-links
	echo "Evaluated $(wc -l original-links | awk '{print $1}') symbolic links"
fi

# Run tests:
COUNT=0
echo -n > $OF
while true; do

	# Delete system artifact
	rm -rf $SYS_ARTIFACT_PATH

	# Rebuild
	BOF="build-$COUNT"
	echo "Run $COUNT: Rebuilding $SYSTEM, log at \`tail -f $(pwd)/$BOF\`" | tee -a $OF
	../ybd/ybd.py $1 $2 | tee $BOF 2>&1 > /dev/null

	(echo "Overlaps:"
	 awk '/WARNING: overlapping path/ {print $NF}' $BOF) | tee -a $OF

	# Test
	PASS=1

	if ! md5sum -c original-md5sums &> md5-result; then
		# Check overlapping files
		PASS=0
	fi

	if [ $THOROUGH -eq 1 ]; then
		# Check all files
		if ! md5sum -c original-md5sums-all-reg-files &> md5-result-all; then
			PASS=0
		fi
	fi

	if [ $LINKS -eq 1 ]; then
		# Check symbolic link destination paths
		echo -n > link-result
		while read entry; do
			FILE=$(echo "$entry" | awk '{print $1}' | sed 's/\(.*\):/\1/')
			NEW=$(file $FILE | awk '{print $NF}')
			ORIG=$(echo $entry | awk '{print $NF}')
			if [ "$ORIG" != "$NEW" ]; then
				SHORTFILE=$(echo $FILE | sed 's/$SYS_UNPACKED//')
				echo "FAILED: $SHORTFILE: orig: $ORIG new: $NEW" >> link-result
				PASS=0
			fi
		done < original-links
	fi

	# Status
	if [ $PASS -eq 0 ]; then
		(
		echo "Run $COUNT failed"
		echo "Result:"
		echo "Overlapping files:"
		cat md5-result | egrep 'FAILED|WARNING:'
		echo "$(cat md5-result | egrep 'FAILED' | wc -l ) files failed checksum"
		if [ $THOROUGH -eq 1 ]; then
			echo 'All files:'
			cat md5-result-all | egrep 'FAILED|WARNING:'
			echo "$(cat md5-result-all | egrep 'FAILED' | wc -l ) files failed checksum"
		fi
		if [ $LINKS -eq 1 ]; then
			echo "Symbolic links:"
			cat link-result
			echo "$(cat link-result | wc -l ) link destinations differ"
		fi
		) | tee -a $OF
	else
		echo "Run $COUNT succeeded" | tee -a $OF
	fi
	COUNT=$(($COUNT+1))

done

