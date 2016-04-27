#!/usr/bin/env python
# Copyright (C) 2012-2016 Codethink Limited
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

# Portions lifted from the morph build tool

import sys
import glob
import os
import re
import tempfile

import app


class ProjectVersionGuesser(object):

    def __init__(self, interesting_files):
        self.interesting_files = interesting_files

    def file_contents(self, repopath):
        filenames = [x for x in self.interesting_files if x in self.repo_ls]
        for filename in filenames:
            yield filename, self.repo_get_file(repopath, filename)

    def repo_ls(self, repopath):
        return os.listdir(repopath)

    def repo_get_file(self, repopath, filename):
        with open(os.path.join(repopath, filename), 'r') as f:
            return f.read()


class AutotoolsVersionGuesser(ProjectVersionGuesser):

    def __init__(self):
        ProjectVersionGuesser.__init__(self, [
            'configure.ac',
            'configure.in',
            'configure.ac.in',
            'configure.in.in',
        ])

    def guess_version(self, repopath):
        version = None
        for filename, data in self.file_contents(repopath):
            # First, try to grep for AC_INIT()
            version = self._check_ac_init(data)
            if version:
                app.log('MANIFEST', 'Version %s detected' % version)
                break

            # Then, try running autoconf against the configure script
            version = self._check_autoconf_package_version(repopath,
                                                           filename,data)
            if version:
                app.log('MANIFEST', 'Version %s detected' % version)
                break
        return version

    def _check_ac_init(self, data):
        data = data.replace('\n', ' ')
        for macro in ['AC_INIT', 'AM_INIT_AUTOMAKE']:
            pattern = r'.*%s\((.*?)\).*' % macro
            if not re.match(pattern, data):
                continue
            acinit = re.sub(pattern, r'\1', data)
            if acinit:
                version = acinit.split(',')
                if macro == 'AM_INIT_AUTOMAKE' and len(version) == 1:
                    continue
                version = version[0] if len(version) == 1 else version[1]
                version = re.sub('[\[\]]', '', version).strip()
                version = version.split()[0]
                if version:
                    if version and version[0].isdigit():
                        return version
        return None

    def _check_autoconf_package_version(self, repopath, filename, data):
        try:
            tempdir = tempfile.mkdtemp()
            tempfile = os.path.join(tempdir, filename)
            with open(tempfile, 'w') as f:
                f.write(data)
            exit_code, output, errors = subprocess.check_call(
                ['autoconf', tempfile],
                ['grep', '^PACKAGE_VERSION='],
                ['cut', '-d=', '-f2'],
                ['sed', "s/'//g"])
            version = None
            if output:
                output = output.strip()
                if output and output[0].isdigit():
                    version = output
            if exit_code != 0:
                status('Failed to detect version from '
                       '%s %s:%s' % (repo, ref, filename))
        finally:
            shutil.rmtree(tempdir)
        return version


class VersionGuesser(object):

    def __init__(self):
        self.guessers = [
            AutotoolsVersionGuesser()
        ]

    def guess_version(self, repopath):
        status('Guessing version of %s %s' % (repo, ref))
        version = None
        try:
            # List files on Baserock cache server
            tree = self.ls_repo(repopath)

            for guesser in self.guessers:
                version = guesser.guess_version(repopath)
                if version:
                    break
        except BaseException as err:
            status('Failed to list files in %s %s' % (repo, ref))
        return version


class ManifestGenerator(object):

    def __init__(self):
        self.version_guesser = VersionGuesser()
        self.manifest_items = dict()
        self.colwidths = dict()

    def add(self, **kwargs):
        self.manifest_items[kwargs['name']] = kwargs     

        # Update column widths
        for key, value in kwargs.iteritems():
            colwidths[key] = max(colwidths.get(key, 0), len(value))

    def get_version(self, name, repo_path):
        '''Try to guess the version of a named artifact'''

        version = self.version_guesser.guess_version(repo_path)

        vstring = version if version is not None else ''
        self.manifest_items[name]['version'] = vstring

        # Update column width
        self.colwidths['version'] = max(colwidths.get('version', 0),
            len(vstring))

    def dump_to_file(self, filepath):
        '''Dump manifest to file'''

        with open(filepath, 'w') as file:
            file.write(self.dump())

    def dump(self):
        '''Dump manifest to string'''

        fmt = self._generate_output_format()
        out = fmt % ('ARTIFACT', 'VERSION', 'REPOSITORY', 'REF')

        # Format information about strata and chunks.
        for type in ('stratum', 'chunk'):
            out += self._format_artifacts(fmt, type)
        return out

    def _generate_output_format(self):
        return '%%-%is\t' \
               '%%-%is\t' \
               '%%-%is\t' \
               '%%-%is' % (
                self.colwidths['cache'],
                self.colwidths['version'],
                self.colwidths['repo'],
                self.colwidths['ref'])

    def _format_artifacts(self, fmt, kind):
        out = ''
        for artifact in sorted(self.manifest_items, key=lambda x: x['name']):
            if artifact['kind'] == kind:
                 out += fmt % (artifact['cache'],
                               artifact['version'],
                               artifact['repo'],
                               artifact.get('ref', '')[:7])
        return out
