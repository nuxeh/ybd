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
import contextlib
import tempfile


class ProjectVersionGuesser(object):

    def __init__(self, interesting_files):
        self.interesting_files = interesting_files

    def file_contents(self, repo, ref, tree):
        filenames = [x for x in self.interesting_files if x in tree]
        for filename in filenames:
            # Retreive file from Baserock cache server
            yield filename, scriptslib.cache_get_file(repo, ref, filename)

    def file_ls(self):


class AutotoolsVersionGuesser(ProjectVersionGuesser):

    def __init__(self):
        ProjectVersionGuesser.__init__(self, [
            'configure.ac',
            'configure.in',
            'configure.ac.in',
            'configure.in.in',
        ])

    def guess_version(self, repo, ref, tree):
        version = None
        for filename, data in self.file_contents(repo, ref, tree):
            # First, try to grep for AC_INIT()
            version = self._check_ac_init(data)
            if version:
                status('Version of %s %s detected '
                       'via %s:AC_INIT: %s' % (repo, ref, filename, version))
                break

            # Then, try running autoconf against the configure script
            version = self._check_autoconf_package_version(
                repo, ref, filename, data)
            if version:
                status('Version of %s %s detected by processing '
                       '%s: %s' % (repo, ref, filename, version))
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

    def _check_autoconf_package_version(self, repo, ref, filename, data):
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

    def guess_version(self, repo, ref):
        status('Guessing version of %s %s' % (repo, ref))
        version = None
        try:
            # List files on Baserock cache server
            tree = scriptslib.cache_ls(repo, ref)

            for guesser in self.guessers:
                version = guesser.guess_version(repo, ref, tree)
                if version:
                    break
        except BaseException as err:
            status('Failed to list files in %s %s' % (repo, ref))
        return version


class ManifestGenerator(object):

    headings = None
    values = None

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
        self.manifest_items['version'] = version

    def dump_to_file(self, filepath):
        '''Dump manifest to file'''

        with open(filepath, 'w') as file:
            file.write(self.dump())

    def dump(self):
        '''Dump manifest to string'''

        fmt = self._generate_output_format()
        out = fmt % ('ARTIFACT', 'REPOSITORY', 'REF', 'COMMIT')

        # Format information about system, strata and chunks.
        for type in ('system', 'stratum', 'chunk'):
            out += self._format_artifacts(fmt, type)

        return out

    def _generate_output_format(self):
        return '%%-%is\t' \
               '%%-%is\t' \
               '%%-%is\t' \
               '%%-%is' % (
                self.colwidths['fst_col'],
                self.colwidths['repo'],
                self.colwidths['original_ref'],
                self.colwidths['sha1'])

    def _format_artifacts(self, fmt, kind):
        out = ''
        fst_col = '%s-%s' % (metadata['cache-key'], version) if artifact
        for artifact in sorted(self.manifest_items, key=lambda x: x['name']):
            if artifact['kind'] == kind:
                 out += fmt % (fst_col,
                               artifact['repo'],
                               artifact['original_ref'],
                               artifact['sha1'][:7])
        return out
