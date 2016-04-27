#!/usr/bin/env python
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

'''A module to build a definition.'''

import os
import sys
import fcntl
import app
from assembly import compose
from deployment import deploy
from definitions import Definitions
import cache
import sandbox
import sandboxlib


print('')
if not os.path.exists('./VERSION'):
    if os.path.basename(os.getcwd()) != 'definitions':
        if os.path.isdir(os.path.join(os.getcwd(), 'definitions')):
            os.chdir(os.path.join(os.getcwd(), 'definitions'))
        else:
            if os.path.isdir(os.path.join(os.getcwd(), '..', 'definitions')):
                os.chdir(os.path.join(os.getcwd(), '..', 'definitions'))

app.setup(sys.argv)
app.cleanup(app.config['tmp'])

with app.timer('TOTAL'):
    tmp_lock = open(os.path.join(app.config['tmp'], 'lock'), 'r')
    fcntl.flock(tmp_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)

    target = os.path.join(app.config['defdir'], app.config['target'])
    app.log('TARGET', 'Target is %s' % target, app.config['arch'])
    with app.timer('DEFINITIONS', 'parsing %s' % app.config['def-version']):
        defs = Definitions()
    with app.timer('CACHE-KEYS', 'cache-key calculations'):
        cache.cache_key(defs, app.config['target'])

    cache.cull(app.config['artifacts'])
    target = defs.get(app.config['target'])
    if app.config['total'] == 0 or (app.config['total'] == 1 and
                                    target.get('kind') == 'cluster'):
        app.exit('ARCH', 'ERROR: no definitions found for', app.config['arch'])

    defs.save_trees()
    if app.config.get('mode', 'normal') == 'keys-only':
        with open('./ybd.result', 'w') as f:
            f.write(target['cache'] + '\n')
        os._exit(0)

    sandbox.executor = sandboxlib.executor_for_platform()
    app.log(app.config['target'], 'Sandbox using %s' % sandbox.executor)
    if sandboxlib.chroot == sandbox.executor:
        app.log(app.config['target'], 'WARNING: using chroot is less safe ' +
                'than using linux-user-chroot')

    if app.config.get('instances'):
        app.spawn()

    while True:
        try:       
            manifest = manifest.ManifestGenerator()
            compose(defs, target, manifest)

            if app.config.get('manifest', True):
                manifest.dump_to_file()

            break
        except KeyboardInterrupt:
            app.log(target, 'Interrupted by user')
            os._exit(1)
        except app.RetryException:
            pass
        except:
            import traceback
            traceback.print_exc()
            app.log(target, 'Exiting: uncaught exception')
            os._exit(1)

    if app.config.get('reproduce'):
        app.log('REPRODUCED',
                'Matched %s of' % len(app.config['reproduced']),
                app.config['tasks'])
        for match in app.config['reproduced']:
            print match[0], match[1]

    if target.get('kind') == 'cluster' and app.config.get('fork') is None:
        with app.timer(target, 'cluster deployment'):
            deploy(defs, target)
