# Copyright (C) 2014-2016  Codethink Limited
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# =*= License: GPL-2 =*=

import os
import random
from subprocess import call, check_output
import contextlib
import fcntl
import errno

import json
from app import config, chdir, exit, timer, elapsed
from app import log, log_riemann, lockfile, RetryException
from cache import cache, cache_key, get_cache, get_remote
import repos
import sandbox
from shutil import copyfile
import time
import datetime
import splitting


def compose(defs, target):
    '''Work through defs tree, building and assembling until target exists'''

    component = defs.get(target)

    # if we can't calculate cache key, we can't create this component
    if cache_key(defs, component) is False:
        return False

    # if this component is already cached, we're done
    if get_cache(defs, component):
        return cache_key(defs, component)

    if config.get('log-verbose'):
        log(target, "Composing", component['name'])

    # if we have a kbas, look there to see if this component exists
    if config.get('kbas-url') and not config.get('reproduce'):
        with claim(defs, component):
            if get_remote(defs, component):
                config['counter'].increment()
                return cache_key(defs, component)

    if component.get('arch') and component['arch'] != config['arch']:
        return None

    with sandbox.setup(component):
        assemble(defs, component)  # bring in 'contents' recursively
        build(defs, component)     # bring in 'build-depends', and run make

    return cache_key(defs, component)


def assemble(defs, component):
    '''Handle creation of composite components (strata, systems, clusters)'''
    systems = component.get('systems', [])
    print '---------------------- ASSEMBLE ------------------------'
    print 'COMPONENT: %s' % component
    print 'SYSTEMS: %s' % repr(systems)
    print 'KIND [chunk]: %s' % component.get('kind', 'chunk')
    print 'FORK: %d' % config.get('fork')
    print '---------------------- ASSEMBLE ------------------------'
    # Only use one YBD fork to build systems
    if component.get('kind', 'chunk') == 'system' and config.get('fork') == 0:
        if component.get('kind', 'chunk') != 'system':
            shuffle(systems)
        for system in systems:
            print "SYSTEM: %s" % system
            print "SYSTEM PATH: %s" % system['path']
            compose(defs, system['path'])
            for subsystem in system.get('subsystems', []):
                print "SUBSYSTEM: %s" % subsystem
                compose(defs, subsystem)

        install_contents(defs, component)


def build(defs, component):
    '''Create an artifact for a single component and add it to the cache'''

    if get_cache(defs, component):
        return

    with claim(defs, component):
        if component.get('kind', 'chunk') == 'chunk':
            install_dependencies(defs, component)
        with timer(component, 'build of %s' % component['cache']): ##
            run_build(defs, component)

        with timer(component, 'artifact creation'): ##
            print "WRITING METADATA ---------------------------"
            splitting.write_metadata(defs, component)
            print "CACHE --------------------------------------"
            cache(defs, component)


def run_build(defs, this):
    ''' This is where we run ./configure, make, make install (for example).
    By the time we get here, all dependencies for component have already
    been assembled.
    '''

    if config.get('mode', 'normal') == 'no-build':
        log(this, 'SKIPPING BUILD: artifact will be empty')
        return

    if this.get('build-mode') != 'bootstrap':
        sandbox.ldconfig(this)

    if this.get('repo'):
        repos.checkout(this)
        this['SOURCE_DATE_EPOCH'] = repos.source_date_epoch(this['build'])

    get_build_commands(defs, this)
    env_vars = sandbox.env_vars_for_build(defs, this)

    log(this, 'Logging build commands to %s' % this['log'])
    for build_step in defs.defaults.build_steps:
        if this.get(build_step):
            log(this, 'Running', build_step)
        for command in this.get(build_step, []):
            command = 'false' if command is False else command
            command = 'true' if command is True else command
            sandbox.run_sandboxed(
                this, command, env=env_vars,
                allow_parallel=('build' in build_step))

    if this.get('devices'):
        sandbox.create_devices(this)

    with open(this['log'], "a") as logfile:
        time_elapsed = elapsed(this['start-time'])
        logfile.write('Elapsed_time: %s\n' % time_elapsed)
        log_riemann(this, 'Artifact_Timer', this['name'], time_elapsed)


def shuffle(contents):
    print "SHUFFLE -------------------------------------------------------"
    if config.get('instances', 1) > 1:
        print "ACTUALLY SHUFFLING"
        random.seed(datetime.datetime.now())
        random.shuffle(contents)


@contextlib.contextmanager
def claim(defs, this):
    print 'CLAIM: %s' % this
    with open(lockfile(defs, this), 'a') as l:
        try:
            fcntl.flock(l, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception as e:
            if e.errno in (errno.EACCES, errno.EAGAIN):
                # flock() will report EACCESS or EAGAIN when the lock fails.
                raise RetryException(defs, this)
            else:
                import traceback
                traceback.print_exc()
                exit(this, 'ERROR: a surprise exception happened', '')
        try:
            yield
        finally:
            if os.path.isfile(lockfile(defs, this)):
                os.remove(lockfile(defs, this))


def install_contents(defs, component):
    '''Install recursed contents of component into component's sandbox.'''

    print 'INSTALL CONTENTS ======================================='

    def install(defs, component, contents):
        print "CONTENTS: %s" % contents
        if component.get('kind', 'chunk') != 'system':
            shuffle(contents)
        for it in contents:
            content = defs.get(it)
#            print 'CONTENT: %s' % content
            print 'SANDBOX: %s' % component['sandbox']
            if os.path.exists(os.path.join(component['sandbox'], 'baserock',
                                           content['name'] + '.meta')):
                print "ALREADY INSTALLED %s" % content['name']
                # content has already been installed
                if config.get('log-verbose'):
                    log(component, 'Already installed', content['name'])
                continue

            if component.get('kind', 'chunk') == 'system':
                artifacts = None

                for stratum in component['strata']:
                    if stratum['path'] == content['path']:
                        artifacts = stratum.get('artifacts')
                        break

                print 'ARTIFACTS: %s' % artifacts

                if artifacts:
                    compose(defs, content)
                    splitting.install_stratum_artifacts(defs, component,
                                                        content, artifacts)
                    continue

            install(defs, component, content.get('contents', []))
            compose(defs, content)
            if content.get('build-mode', 'staging') != 'bootstrap':
                sandbox.install(defs, component, content)

    component = defs.get(component)
    contents = component.get('contents', [])
    if config.get('log-verbose'):
        log(component, 'Installing contents\n', contents)
    install(defs, component, contents)
    if config.get('log-verbose'):
        sandbox.list_files(component)


def install_dependencies(defs, component):
    '''Install recursed dependencies of component into component's sandbox.'''

    print 'INSTALL DEPENDENCIES ==================================='

    def install(defs, component, dependencies):
        if component.get('kind', 'chunk') != 'system':
            shuffle(dependencies)
        for it in dependencies:
            dependency = defs.get(it)
            if os.path.exists(os.path.join(component['sandbox'], 'baserock',
                                           dependency['name'] + '.meta')):
                # dependency has already been installed
                if config.get('log-verbose'):
                    log(component, 'Already installed', dependency['name'])
                continue

            install(defs, component, dependency.get('build-depends', []))
            if (it in component['build-depends']) or \
                (dependency.get('build-mode', 'staging') ==
                    component.get('build-mode', 'staging')):
                compose(defs, dependency)
                if dependency.get('contents'):
                    install(defs, component, dependency.get('contents'))
                sandbox.install(defs, component, dependency)

    component = defs.get(component)
    dependencies = component.get('build-depends', [])
    if config.get('log-verbose'):
        log(component, 'Installing dependencies\n', dependencies)
    install(defs, component, dependencies)
    if config.get('log-verbose'):
        sandbox.list_files(component)


def get_build_commands(defs, this):
    '''Get commands specified in 'this', plus commands implied by build-system

    The containing definition may point to another definition file (using
    the 'path' field in YBD's internal data model) that contains build
    instructions, or it may only specify a predefined build system, using
    'build-system' field.

    The definition containing build instructions can specify a predefined
    build-system and then override some or all of the command sequences it
    defines.

    If the definition file doesn't exist and no build-system is specified,
    this function will scan the contents the checked-out source repo and try
    to autodetect what build system is used.

    '''

    if this.get('kind', None) == "system":
        # Systems must run their integration scripts as install commands
        this['install-commands'] = gather_integration_commands(defs, this)
        return

    if this.get('build-system') or os.path.exists(this['path']):
        bs = this.get('build-system', 'manual')
        log(this, 'Defined build system is', bs)
    else:
        files = os.listdir(this['build'])
        bs = defs.defaults.detect_build_system(files)
        log(this, 'WARNING: Autodetected build system is', bs)

    for build_step in defs.defaults.build_steps:
        if this.get(build_step, None) is None:
            commands = defs.defaults.build_systems[bs].get(build_step, [])
            this[build_step] = commands


def gather_integration_commands(defs, this):
    # 1. iterate all subcomponents (recursively) looking for sys-int commands
    # 2. gather them all up
    # 3. asciibetically sort them
    # 4. concat the lists

    def _gather_recursively(component, commands):
        if 'system-integration' in component:
            for product, it in component['system-integration'].iteritems():
                for name, cmdseq in it.iteritems():
                    commands["%s-%s" % (name, product)] = cmdseq
        for subcomponent in component.get('contents', []):
            _gather_recursively(defs.get(subcomponent), commands)

    all_commands = {}
    _gather_recursively(this, all_commands)
    result = []
    for key in sorted(all_commands.keys()):
        result.extend(all_commands[key])
    return result
