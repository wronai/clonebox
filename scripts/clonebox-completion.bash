#!/bin/bash
# CloneBox bash completion script
# Install: source this file or add to ~/.bashrc
#   source /path/to/clonebox-completion.bash
# Or copy to /etc/bash_completion.d/clonebox

_clonebox_completions() {
    local cur prev opts commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Main commands
    commands="create start open stop restart delete list ls container dashboard detect clone status diagnose diag watch repair export import test monitor exec keygen export-encrypted import-encrypted export-remote import-remote sync-key list-remote"

    # Container subcommands
    container_commands="up ps ls stop rm down"

    # Options that take VM name or path
    vm_opts="start open stop restart delete status diagnose diag watch repair export test exec"

    case "${prev}" in
        clonebox)
            COMPREPLY=( $(compgen -W "${commands} --version --help" -- "${cur}") )
            return 0
            ;;
        container)
            COMPREPLY=( $(compgen -W "${container_commands}" -- "${cur}") )
            return 0
            ;;
        --profile)
            # Suggest built-in profiles
            COMPREPLY=( $(compgen -W "ml-dev web-stack" -- "${cur}") )
            return 0
            ;;
        --engine)
            COMPREPLY=( $(compgen -W "auto podman docker" -- "${cur}") )
            return 0
            ;;
        --network)
            COMPREPLY=( $(compgen -W "auto default user" -- "${cur}") )
            return 0
            ;;
        -o|--output)
            # File completion
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0
            ;;
        --base-image)
            # .qcow2 files
            COMPREPLY=( $(compgen -f -X '!*.qcow2' -- "${cur}") )
            return 0
            ;;
        export-remote|import-remote|sync-key|list-remote)
            # Suggest user@host format
            COMPREPLY=( $(compgen -A hostname -- "${cur}") )
            return 0
            ;;
    esac

    # Command-specific options
    case "${COMP_WORDS[1]}" in
        start|open|stop|restart|delete|status|diagnose|diag|watch|repair|test|exec)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-u --user -h --help" -- "${cur}") )
            else
                # Suggest VM names from virsh list
                local vms
                vms=$(virsh --connect qemu:///session list --all --name 2>/dev/null | grep -v '^$')
                vms="${vms} ."
                COMPREPLY=( $(compgen -W "${vms}" -- "${cur}") )
            fi
            return 0
            ;;
        clone)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-u --user -n --name -r --run -e --edit --profile --network --base-image --disk-size-gb --replace --dry-run -h --help" -- "${cur}") )
            else
                # Directory completion
                COMPREPLY=( $(compgen -d -- "${cur}") )
            fi
            return 0
            ;;
        export)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-u --user -o --output -d --include-data -h --help" -- "${cur}") )
            fi
            return 0
            ;;
        import)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-u --user --replace -h --help" -- "${cur}") )
            else
                COMPREPLY=( $(compgen -f -X '!*.tar.gz' -- "${cur}") )
            fi
            return 0
            ;;
        export-encrypted)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-u --user -o --output --user-data -d --include-data -h --help" -- "${cur}") )
            fi
            return 0
            ;;
        import-encrypted)
            if [[ "${cur}" == -* ]]; then
                COMPREPLY=( $(compgen -W "-u --user -n --name --user-data -d --include-data -h --help" -- "${cur}") )
            else
                COMPREPLY=( $(compgen -f -X '!*.enc' -- "${cur}") )
            fi
            return 0
            ;;
        container)
            case "${COMP_WORDS[2]}" in
                up)
                    if [[ "${cur}" == -* ]]; then
                        COMPREPLY=( $(compgen -W "--engine --name --image --detach --profile --mount --port --package --no-dotenv -h --help" -- "${cur}") )
                    else
                        COMPREPLY=( $(compgen -d -- "${cur}") )
                    fi
                    ;;
                ps|ls)
                    COMPREPLY=( $(compgen -W "--engine -a --all --json -h --help" -- "${cur}") )
                    ;;
                stop|rm)
                    if [[ "${cur}" == -* ]]; then
                        COMPREPLY=( $(compgen -W "--engine -f --force -h --help" -- "${cur}") )
                    else
                        # Suggest container names
                        local containers
                        containers=$(podman ps -a --format '{{.Names}}' 2>/dev/null || docker ps -a --format '{{.Names}}' 2>/dev/null)
                        COMPREPLY=( $(compgen -W "${containers}" -- "${cur}") )
                    fi
                    ;;
                down)
                    if [[ "${cur}" == -* ]]; then
                        COMPREPLY=( $(compgen -W "--engine -h --help" -- "${cur}") )
                    fi
                    ;;
            esac
            return 0
            ;;
        dashboard)
            COMPREPLY=( $(compgen -W "--port -h --help" -- "${cur}") )
            return 0
            ;;
        monitor)
            COMPREPLY=( $(compgen -W "-u --user -r --refresh --once -h --help" -- "${cur}") )
            return 0
            ;;
        detect)
            COMPREPLY=( $(compgen -W "--json --yaml --dedupe -o --output -h --help" -- "${cur}") )
            return 0
            ;;
    esac

    # Default: suggest commands
    if [[ "${cur}" == -* ]]; then
        COMPREPLY=( $(compgen -W "--version --help" -- "${cur}") )
    else
        COMPREPLY=( $(compgen -W "${commands}" -- "${cur}") )
    fi
}

complete -F _clonebox_completions clonebox
