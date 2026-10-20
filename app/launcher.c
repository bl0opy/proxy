// Bundle executable for Proxy.app. It spawns the venv's Python as a child
// rather than exec'ing it, so macOS attributes microphone, input monitoring and
// accessibility to Proxy.app (the responsible process), the same way a shell's
// children inherit Terminal's permissions.
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

#ifndef PROJECT_DIR
#error "build with -DPROJECT_DIR=\"/path/to/proxy\""
#endif

#define RESTART_STATUS 75

extern char **environ;
static pid_t child = 0;

static void forward(int sig) {
    if (child > 0) kill(child, sig);
}

int main(void) {
    char python[PATH_MAX], logdir[PATH_MAX], logpath[PATH_MAX];
    snprintf(python, sizeof python, "%s/.venv/bin/python", PROJECT_DIR);
    snprintf(logdir, sizeof logdir, "%s/Library/Logs/Proxy", getenv("HOME"));
    snprintf(logpath, sizeof logpath, "%s/proxy.log", logdir);
    mkdir(logdir, 0755);

    if (chdir(PROJECT_DIR) != 0) return 1;
    setenv("PYTHONUNBUFFERED", "1", 1);
    setenv("PROXY_APP", "1", 1);
    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);

    posix_spawn_file_actions_t files;
    posix_spawn_file_actions_init(&files);
    posix_spawn_file_actions_addopen(&files, STDOUT_FILENO, logpath, O_WRONLY | O_CREAT | O_APPEND, 0644);
    posix_spawn_file_actions_adddup2(&files, STDOUT_FILENO, STDERR_FILENO);
    char *args[] = {python, "-m", "proxy", "--listen", NULL};

    int status = 0;
    do {
        if (posix_spawn(&child, python, &files, NULL, args, environ) != 0) return 1;
        while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
    } while (WIFEXITED(status) && WEXITSTATUS(status) == RESTART_STATUS);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
