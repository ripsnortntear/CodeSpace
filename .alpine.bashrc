# ~/.bashrc: executed by bash(1) for non-login shells.

# Enable color support for ls and grep
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)"
    alias ls='ls --color=auto'
    alias grep='grep --color=auto'
fi

# Set up the prompt with time, user, host, and current directory
PS1='$\e[32m$\A $\e[34m$\u@\h $\e[36m$\w$\e[0m$\$ '

# Enable command history
HISTSIZE=1000
HISTFILESIZE=2000
HISTCONTROL=ignoredups:erasedups  # no duplicate entries

# Aliases for convenience
alias ll='ls -la'
alias la='ls -A'
alias l='ls -CF'
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias cls='clear'
alias c='clear'

# Enable auto-completion
if [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
fi

# Set the default editor
export EDITOR=nano

# Set the terminal title
case $TERM in
    xterm*|rxvt*)
        PROMPT_COMMAND='echo -ne "\033]0;${USER}@${HOSTNAME}: ${PWD}\007"'
        ;;
esac

# Enable colored man pages
export MANPAGER="less -R"

# Custom functions
mkcd() {
    mkdir -p "$1" && cd "$1"
}

# Load additional scripts if they exist
if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# Source the bash completion if available
if [ -f /etc/bash_completion ]; then
    . /etc/bash_completion
fi

# Set the PATH
export PATH="$HOME/bin:$PATH"

# Load the .bashrc file
if [ -f ~/.bashrc ]; then
    . ~/.bashrc
fi
