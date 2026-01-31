#compdef clonebox
# CloneBox zsh completion script
# Install: Add to fpath or source this file
#   fpath=(/path/to/dir $fpath)
#   autoload -Uz compinit && compinit
# Or: source /path/to/clonebox-completion.zsh

_clonebox() {
    local curcontext="$curcontext" state line
    typeset -A opt_args

    local -a commands
    commands=(
        'create:Create VM from config'
        'start:Start a VM'
        'open:Open VM viewer window'
        'stop:Stop a VM'
        'restart:Restart a VM'
        'delete:Delete a VM'
        'list:List VMs'
        'ls:List VMs (alias)'
        'container:Manage container sandboxes'
        'dashboard:Run local dashboard'
        'detect:Detect system state'
        'clone:Generate clone config from path'
        'status:Check VM status and health'
        'diagnose:Run detailed VM diagnostics'
        'diag:Run diagnostics (alias)'
        'watch:Watch boot diagnostic output'
        'repair:Trigger repair inside VM'
        'export:Export VM and data'
        'import:Import VM from archive'
        'test:Test VM configuration'
        'monitor:Real-time resource monitoring'
        'exec:Execute command in VM'
        'keygen:Generate encryption key'
        'export-encrypted:Export VM with AES-256 encryption'
        'import-encrypted:Import VM with decryption'
        'export-remote:Export VM from remote host'
        'import-remote:Import VM to remote host'
        'sync-key:Sync encryption key to remote'
        'list-remote:List VMs on remote host'
    )

    local -a container_commands
    container_commands=(
        'up:Start container'
        'ps:List containers'
        'ls:List containers (alias)'
        'stop:Stop container'
        'rm:Remove container'
        'down:Stop and remove container'
    )

    _arguments -C \
        '--version[Show version]' \
        '--help[Show help]' \
        '1: :->command' \
        '*:: :->args'

    case $state in
        command)
            _describe -t commands 'clonebox command' commands
            ;;
        args)
            case $words[1] in
                start|open|stop|restart|delete|status|diagnose|diag|watch|repair|test|exec)
                    _arguments \
                        '-u[Use user session]' \
                        '--user[Use user session]' \
                        '--help[Show help]' \
                        '1:VM name:_clonebox_vms'
                    ;;
                clone)
                    _arguments \
                        '-u[Use user session]' \
                        '--user[Use user session]' \
                        '-n[VM name]:name' \
                        '--name[VM name]:name' \
                        '-r[Create and start VM]' \
                        '--run[Create and start VM]' \
                        '-e[Edit config before creating]' \
                        '--edit[Edit config before creating]' \
                        '--profile[Profile name]:profile:(ml-dev web-stack)' \
                        '--network[Network mode]:mode:(auto default user)' \
                        '--base-image[Base qcow2 image]:file:_files -g "*.qcow2"' \
                        '--disk-size-gb[Disk size in GB]:size' \
                        '--replace[Replace existing VM]' \
                        '--dry-run[Show what would be created]' \
                        '--help[Show help]' \
                        '1:path:_files -/'
                    ;;
                export)
                    _arguments \
                        '-u[Use user session]' \
                        '--user[Use user session]' \
                        '-o[Output file]:file:_files' \
                        '--output[Output file]:file:_files' \
                        '-d[Include app data]' \
                        '--include-data[Include app data]' \
                        '--help[Show help]' \
                        '1:VM name:_clonebox_vms'
                    ;;
                import)
                    _arguments \
                        '-u[Use user session]' \
                        '--user[Use user session]' \
                        '--replace[Replace existing VM]' \
                        '--help[Show help]' \
                        '1:archive:_files -g "*.tar.gz"'
                    ;;
                export-encrypted)
                    _arguments \
                        '-u[Use user session]' \
                        '--user[Use user session]' \
                        '-o[Output file]:file:_files' \
                        '--output[Output file]:file:_files' \
                        '--user-data[Include user data]' \
                        '-d[Include app data]' \
                        '--include-data[Include app data]' \
                        '--help[Show help]' \
                        '1:VM name:_clonebox_vms'
                    ;;
                import-encrypted)
                    _arguments \
                        '-u[Use user session]' \
                        '--user[Use user session]' \
                        '-n[New VM name]:name' \
                        '--name[New VM name]:name' \
                        '--user-data[Import user data]' \
                        '-d[Import app data]' \
                        '--include-data[Import app data]' \
                        '--help[Show help]' \
                        '1:archive:_files -g "*.enc"'
                    ;;
                export-remote)
                    _arguments \
                        '-o[Output file]:file:_files' \
                        '--output[Output file]:file:_files' \
                        '-e[Use encryption]' \
                        '--encrypted[Use encryption]' \
                        '--user-data[Include user data]' \
                        '-d[Include app data]' \
                        '--include-data[Include app data]' \
                        '--help[Show help]' \
                        '1:host:_hosts' \
                        '2:vm_name'
                    ;;
                import-remote|sync-key|list-remote)
                    _arguments \
                        '--help[Show help]' \
                        '1:host:_hosts'
                    ;;
                container)
                    _arguments -C \
                        '1: :->container_command' \
                        '*:: :->container_args'
                    case $state in
                        container_command)
                            _describe -t commands 'container command' container_commands
                            ;;
                        container_args)
                            case $words[1] in
                                up)
                                    _arguments \
                                        '--engine[Container engine]:engine:(auto podman docker)' \
                                        '--name[Container name]:name' \
                                        '--image[Container image]:image' \
                                        '--detach[Run in background]' \
                                        '--profile[Profile name]:profile:(ml-dev web-stack)' \
                                        '--mount[Extra mount]:mount' \
                                        '--port[Port mapping]:port' \
                                        '--package[Package to install]:package' \
                                        '--no-dotenv[Skip .env file]' \
                                        '--help[Show help]' \
                                        '1:path:_files -/'
                                    ;;
                                ps|ls)
                                    _arguments \
                                        '--engine[Container engine]:engine:(auto podman docker)' \
                                        '-a[Show all containers]' \
                                        '--all[Show all containers]' \
                                        '--json[Output JSON]' \
                                        '--help[Show help]'
                                    ;;
                                stop|rm)
                                    _arguments \
                                        '--engine[Container engine]:engine:(auto podman docker)' \
                                        '-f[Force]' \
                                        '--force[Force]' \
                                        '--help[Show help]' \
                                        '1:container:_clonebox_containers'
                                    ;;
                                down)
                                    _arguments \
                                        '--engine[Container engine]:engine:(auto podman docker)' \
                                        '--help[Show help]' \
                                        '1:container:_clonebox_containers'
                                    ;;
                            esac
                            ;;
                    esac
                    ;;
                dashboard)
                    _arguments \
                        '--port[Port to bind]:port' \
                        '--help[Show help]'
                    ;;
                monitor)
                    _arguments \
                        '-u[Use user session]' \
                        '--user[Use user session]' \
                        '-r[Refresh interval]:seconds' \
                        '--refresh[Refresh interval]:seconds' \
                        '--once[Show once and exit]' \
                        '--help[Show help]'
                    ;;
                detect)
                    _arguments \
                        '--json[Output JSON]' \
                        '--yaml[Output YAML]' \
                        '--dedupe[Remove duplicates]' \
                        '-o[Output file]:file:_files' \
                        '--output[Output file]:file:_files' \
                        '--help[Show help]'
                    ;;
            esac
            ;;
    esac
}

_clonebox_vms() {
    local -a vms
    vms=(${(f)"$(virsh --connect qemu:///session list --all --name 2>/dev/null | grep -v '^$')"})
    vms+=('.')
    _describe -t vms 'VM name' vms
}

_clonebox_containers() {
    local -a containers
    containers=(${(f)"$(podman ps -a --format '{{.Names}}' 2>/dev/null || docker ps -a --format '{{.Names}}' 2>/dev/null)"})
    _describe -t containers 'container name' containers
}

_clonebox "$@"
