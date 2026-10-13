# Retire cached legacy expansions when this file is sourced in an existing shell.
abbr --erase gmmax gmno gmmed gmrol gmlow qw

function gen --description 'Control one local model through systemd user'
    # Keep model launchers untouched; the controller serializes lifecycle operations.
    command /usr/bin/python3 -B /home/alex/.config/my_scripts/gen/gen.py $argv
end
