#!/usr/bin/env bash

# assets/asciicast should contain xz-compressed asciinema-generated files, i.e. *.cast.xz files.
# assets/images should contain directories:
# - generated by Moulti's "save" feature
# - named "{columns}x{lines}-{title}", e.g. "110x36-first-steps-1"
# - with an optional "moulti.css" TCSS file
# - with an optional "input" executable file
# - with an optional "postprocess" executable file

function postprocess_svg {
	local svg="${1?}"
	# Reindent using tabs and long lines:
	xmlindent -t -l 1000 -w "${svg}" && rm -f "${svg}~"
	# Remove window decorations:
	# 1 - remove all items between </style> and the first </g>
	perl -i -nlE 'if (m#</style>#) { say; $window = 1; } say unless $window; $window = 0 if ($window && m#</g>#);' "${svg}"
	# 2 - un-translate the terminal now that decorations have been removed:
	perl -i -plE 'if (!$replaced && m#<g transform="translate\(\d+, \d+\)"#) { s# transform="translate\(\d+, \d+\)"##; $replaced = 1; }' "${svg}"
	# 3 - reduce the viewbox now that decorations have been removed:
	perl -i -plE 's#viewBox="0 0 ([0-9.]+) ([0-9.]+)"# ($w, $h) = ($1 -9 -10, $2 -41 -6); qq[viewBox="0 0 $w $h"]#e' "${svg}"
}


# Part 1: uncompress asciicasts:
in_dir='assets/asciicast'
out_dir='docs/assets/asciicasts'

mkdir -p "${out_dir}"
while read asciicast; do
	xzcat "${in_dir}/${asciicast}" > "${out_dir}/${asciicast/.xz/}"
done < <(find "${in_dir}/" -mindepth 1 -maxdepth 2 -type f -name '*.cast.xz' -printf '%P\n')

# Part 2: download asciinema files:
out_dir='docs/assets/asciinema'

mkdir -p "${out_dir}"
asciinema_release='v3.9.0'
asciinema_base_url="https://github.com/asciinema/asciinema-player/releases/download/${asciinema_release}/"
for filename in asciinema-player.{css,min.js}; do
	[ -e "${out_dir}/${filename}" ] || curl -sL "${asciinema_base_url}/${filename}" > "${out_dir}/${filename}"
done

# Part 3: generate screenshots:
in_dir='assets/images'
out_dir='docs/assets/images'

mkdir -p "${out_dir}"
unset MOULTI_CUSTOM_CSS
export TEXTUAL_SCREENSHOT=1
export TEXTUAL_SCREENSHOT_LOCATION="${out_dir}"

while read src; do
	if [[ "${src}" =~ ^([0-9]+)x([0-9]+)-(.*) ]]; then
		columns="${BASH_REMATCH[1]}"
		lines="${BASH_REMATCH[2]}"
		svg="${BASH_REMATCH[3]}.svg"
		[ -f "${out_dir}/${svg}" ] && continue
		export TEXTUAL_SCREENSHOT_FILENAME="${svg}"

		# Set optional, image-specific CSS:
		unset MOULTI_CUSTOM_CSS
		[ -f "${in_dir}/${src}/moulti.css" ] && export MOULTI_CUSTOM_CSS=$(readlink -f "${in_dir}/${src}/moulti.css")

		# Take a screenshot, driven by either image-specific input or the current terminal:
		if [ -x "${in_dir}/${src}/input" ]; then
			 "${in_dir}/${src}/input" | COLUMNS="${columns}" LINES="${lines}" moulti run -- moulti load "${in_dir}/${src}"
		else
			COLUMNS="${columns}" LINES="${lines}" moulti run -- moulti load "${in_dir}/${src}" < /dev/tty
		fi

		# Postprocessing:
		if [ -f "${out_dir}/${svg}" ]; then
			# Mandatory, generic postprocessing:
			postprocess_svg "${out_dir}/${svg}"
			# Optional, image-specific postprocessing:
			[ -x "${in_dir}/${src}/postprocess" ] && "${in_dir}/${src}/postprocess" "${out_dir}/${svg}"
		fi
	fi
done < <(find "${in_dir}/" -mindepth 1 -maxdepth 2 -type d -printf '%P\n')
