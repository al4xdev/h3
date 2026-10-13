complete -c gen -f
complete -c gen -n '__fish_use_subcommand' -a 'image imagem video qw' -d 'Iniciar perfil preservado'
complete -c gen -n '__fish_use_subcommand' -a stop -d 'Parar somente o serviço gen'
complete -c gen -n '__fish_use_subcommand' -a status -d 'Consultar estado sem iniciar modelos'
complete -c gen -n '__fish_use_subcommand' -a logs -d 'Ler logs por linhas: gen logs 100 200'
complete -c gen -n '__fish_seen_subcommand_from status' -l json -d 'Estado estruturado'
complete -c gen -n '__fish_seen_subcommand_from logs' -l run -d 'Execução histórica por ID' -r
complete -c gen -s h -l help -d 'Mostrar ajuda'
