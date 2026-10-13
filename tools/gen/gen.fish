function gen --description 'Controla um único modelo local via systemd user'
    # Keep model launchers untouched; the controller serializes lifecycle operations.
    command /usr/bin/python3 /home/alex/git/my/h3/tools/gen/gen.py $argv
end
