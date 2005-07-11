"""setuptools.command.bdist_egg

Build .egg distributions"""

# This module should be kept compatible with Python 2.3
import os, marshal
from setuptools import Command
from distutils.dir_util import remove_tree, mkpath
from distutils.sysconfig import get_python_version, get_python_lib
from distutils import log
from pkg_resources import get_platform, Distribution
from types import CodeType

def write_stub(resource, pyfile):
    f = open(pyfile,'w')
    f.write('\n'.join([
        "def __bootstrap__():",
        "   global __bootstrap__, __loader__, __file__",
        "   import sys, pkg_resources, imp",
        "   __file__ = pkg_resources.resource_filename(__name__,%r)"
            % resource,
        "   del __bootstrap__, __loader__",
        "   imp.load_dynamic(__name__,__file__)",
        "__bootstrap__()",
        "" # terminal \n
    ]))
    f.close()














class bdist_egg(Command):

    description = "create an \"egg\" distribution"

    user_options = [
        ('bdist-dir=', 'b',
            "temporary directory for creating the distribution"),
        ('plat-name=', 'p',
                     "platform name to embed in generated filenames "
                     "(default: %s)" % get_platform()),
        ('exclude-source-files', None,
                     "remove all .py files from the generated egg"),
        ('keep-temp', 'k',
                     "keep the pseudo-installation tree around after " +
                     "creating the distribution archive"),
        ('dist-dir=', 'd',
                     "directory to put final built distributions in"),
        ('skip-build', None,
                     "skip rebuilding everything (for testing/debugging)"),
    ]

    boolean_options = [
        'keep-temp', 'skip-build', 'exclude-source-files'
    ]

















    def initialize_options (self):
        self.bdist_dir = None
        self.plat_name = None
        self.keep_temp = 0
        self.dist_dir = None
        self.skip_build = 0
        self.egg_output = None
        self.exclude_source_files = None


    def finalize_options(self):
        ei_cmd = self.get_finalized_command("egg_info")
        self.egg_info = ei_cmd.egg_info

        if self.bdist_dir is None:
            bdist_base = self.get_finalized_command('bdist').bdist_base
            self.bdist_dir = os.path.join(bdist_base, 'egg')

        if self.plat_name is None:
            self.plat_name = get_platform()

        self.set_undefined_options('bdist',('dist_dir', 'dist_dir'))

        if self.egg_output is None:

            # Compute filename of the output egg
            basename = Distribution(
                None, None, ei_cmd.egg_name, ei_cmd.egg_version,
                get_python_version(),
                self.distribution.has_ext_modules() and self.plat_name
            ).egg_name()

            self.egg_output = os.path.join(self.dist_dir, basename+'.egg')








    def do_install_data(self):
        # Hack for packages that install data to install's --install-lib
        self.get_finalized_command('install').install_lib = self.bdist_dir

        site_packages = os.path.normcase(os.path.realpath(get_python_lib()))
        old, self.distribution.data_files = self.distribution.data_files,[]

        for item in old:
            if isinstance(item,tuple) and len(item)==2:
                if os.path.isabs(item[0]):
                    realpath = os.path.realpath(item[0])
                    normalized = os.path.normcase(realpath)
                    if normalized==site_packages or normalized.startswith(
                        site_packages+os.sep
                    ):
                        item = realpath[len(site_packages)+1:], item[1]
                    # XXX else: raise ???
            self.distribution.data_files.append(item)

        try:
            log.info("installing package data to %s" % self.bdist_dir)
            self.call_command('install_data', force=0, root=None)
        finally:
            self.distribution.data_files = old


    def get_outputs(self):
        return [self.egg_output]


    def call_command(self,cmdname,**kw):
        """Invoke reinitialized command `cmdname` with keyword args"""
        for dirname in INSTALL_DIRECTORY_ATTRS:
            kw.setdefault(dirname,self.bdist_dir)
        kw.setdefault('skip_build',self.skip_build)
        kw.setdefault('dry_run', self.dry_run)
        cmd = self.reinitialize_command(cmdname, **kw)
        self.run_command(cmdname)
        return cmd


    def run(self):
        # Generate metadata first
        self.run_command("egg_info")

        # We run install_lib before install_data, because some data hacks
        # pull their data path from the install_lib command.
        
        log.info("installing library code to %s" % self.bdist_dir)
        cmd = self.call_command('install_lib', warn_dir=0)

        ext_outputs = cmd._mutate_outputs(
            self.distribution.has_ext_modules(), 'build_ext', 'build_lib', ''
        )
        self.stubs = []
        to_compile = []
        for (p,ext_name) in enumerate(ext_outputs):
            filename,ext = os.path.splitext(ext_name)
            pyfile = os.path.join(self.bdist_dir, filename + '.py')
            self.stubs.append(pyfile)
            log.info("creating stub loader for %s" % ext_name)
            if not self.dry_run:
                write_stub(os.path.basename(ext_name), pyfile)
            to_compile.append(pyfile)
            ext_outputs[p] = ext_name.replace(os.sep,'/')

        if to_compile:
            cmd.byte_compile(to_compile)

        if self.distribution.data_files:
            self.do_install_data()

        # Make the EGG-INFO directory
        archive_root = self.bdist_dir
        egg_info = os.path.join(archive_root,'EGG-INFO')
        self.mkpath(egg_info)

        if self.distribution.scripts:
            script_dir = os.path.join(egg_info, 'scripts')
            log.info("installing scripts to %s" % script_dir)
            self.call_command('install_scripts', install_dir=script_dir)

        native_libs = os.path.join(self.egg_info,"native_libs.txt")
        if ext_outputs:
            log.info("writing %s" % native_libs)
            if not self.dry_run:
                libs_file = open(native_libs, 'wt')
                libs_file.write('\n'.join(ext_outputs))
                libs_file.write('\n')
                libs_file.close()
        elif os.path.isfile(native_libs):
            log.info("removing %s" % native_libs)
            if not self.dry_run:
                os.unlink(native_libs)

        for filename in os.listdir(self.egg_info):
            path = os.path.join(self.egg_info,filename)
            if os.path.isfile(path):
                self.copy_file(path,os.path.join(egg_info,filename))

        write_safety_flag(archive_root, self.zip_safe())

        if os.path.exists(os.path.join(self.egg_info,'depends.txt')):
            log.warn(
                "WARNING: 'depends.txt' will not be used by setuptools 0.6!\n"
                "Use the install_requires/extras_require setup() args instead."
            )

        if self.exclude_source_files:
            self.zap_pyfiles()
        
        # Make the archive
        make_zipfile(self.egg_output, archive_root, verbose=self.verbose,
                          dry_run=self.dry_run)
        if not self.keep_temp:
            remove_tree(self.bdist_dir, dry_run=self.dry_run)

        # Add to 'Distribution.dist_files' so that the "upload" command works
        getattr(self.distribution,'dist_files',[]).append(
            ('bdist_egg',get_python_version(),self.egg_output))



    def zap_pyfiles(self):
        log.info("Removing .py files from temporary directory")
        for base,dirs,files in walk_egg(self.bdist_dir):
            for name in files:
                if name.endswith('.py'):
                    path = os.path.join(base,name)
                    log.debug("Deleting %s", path)
                    os.unlink(path)

    def zip_safe(self):
        safe = getattr(self.distribution,'zip_safe',None)
        if safe is not None:
            return safe
        log.warn("zip_safe flag not set; analyzing archive contents...")
        return analyze_egg(self.bdist_dir, self.stubs)


























def walk_egg(egg_dir):
    """Walk an unpacked egg's contents, skipping the metadata directory"""
    walker = os.walk(egg_dir)
    base,dirs,files = walker.next()       
    if 'EGG-INFO' in dirs:
        dirs.remove('EGG-INFO')
    yield base,dirs,files
    for bdf in walker:
        yield bdf

def analyze_egg(egg_dir, stubs):
    safe = True
    for base, dirs, files in walk_egg(egg_dir):
        for name in files:
            if name.endswith('.py') or name.endswith('.pyw'):
                continue
            elif name.endswith('.pyc') or name.endswith('.pyo'):
                # always scan, even if we already know we're not safe
                safe = scan_module(egg_dir, base, name, stubs) and safe
            '''elif safe:
                log.warn(
                    "Distribution contains data or extensions; assuming "
                    "it's unsafe (set zip_safe=True in setup() to change"
                )
                safe = False    # XXX'''
    return safe

def write_safety_flag(egg_dir, safe):
    # Write a zip safety flag file
    flag = safe and 'zip-safe' or 'not-zip-safe'
    open(os.path.join(egg_dir,'EGG-INFO',flag),'w').close()










def scan_module(egg_dir, base, name, stubs):
    """Check whether module possibly uses unsafe-for-zipfile stuff"""

    filename = os.path.join(base,name)
    if filename[:-1] in stubs:
        return True     # Extension module

    pkg = base[len(egg_dir)+1:].replace(os.sep,'.')
    module = pkg+(pkg and '.' or '')+os.path.splitext(name)[0]

    f = open(filename,'rb'); f.read(8)   # skip magic & date
    code = marshal.load(f);  f.close()
    safe = True

    symbols = dict.fromkeys(iter_symbols(code))
    for bad in ['__file__', '__path__']:
        if bad in symbols:
            log.warn("%s: module references %s", module, bad)
            safe = False
    if 'inspect' in symbols:
        for bad in [
            'getsource', 'getabsfile', 'getsourcefile', 'getfile'
            'getsourcelines', 'findsource', 'getcomments', 'getframeinfo',
            'getinnerframes', 'getouterframes', 'stack', 'trace'
        ]:
            if bad in symbols:
                log.warn("%s: module MAY be using inspect.%s", module, bad)
                safe = False           
    return safe

def iter_symbols(code):
    """Yield names and strings used by `code` and its nested code objects"""
    for name in code.co_names: yield name
    for const in code.co_consts:
        if isinstance(const,basestring):
            yield const
        elif isinstance(const,CodeType):
            for name in iter_symbols(const):
                yield name


# Attribute names of options for commands that might need to be convinced to
# install to the egg build directory

INSTALL_DIRECTORY_ATTRS = [
    'install_lib', 'install_dir', 'install_data', 'install_base'
]


def make_zipfile (zip_filename, base_dir, verbose=0, dry_run=0):
    """Create a zip file from all the files under 'base_dir'.  The output
    zip file will be named 'base_dir' + ".zip".  Uses either the "zipfile"
    Python module (if available) or the InfoZIP "zip" utility (if installed
    and found on the default search path).  If neither tool is available,
    raises DistutilsExecError.  Returns the name of the output zip file.
    """
    import zipfile
    mkpath(os.path.dirname(zip_filename), dry_run=dry_run)

    log.info("creating '%s' and adding '%s' to it", zip_filename, base_dir)

    def visit (z, dirname, names):
        for name in names:
            path = os.path.normpath(os.path.join(dirname, name))
            if os.path.isfile(path):
                p = path[len(base_dir)+1:]
                if not dry_run:
                    z.write(path, p)
                log.debug("adding '%s'" % p)

    if not dry_run:
        z = zipfile.ZipFile(zip_filename, "w",
                            compression=zipfile.ZIP_DEFLATED)
        os.path.walk(base_dir, visit, z)
        z.close()
    else:
        os.path.walk(base_dir, visit, None)

    return zip_filename



