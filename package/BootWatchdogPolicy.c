// SPDX-License-Identifier: MIT
// penang: UniXNU-sheng package/BootWatchdogPolicy.c (launchd's disabled.plist before launchd starts), called from load_init_program
// after the Data mount (patches/xnu/penang-launchd-job-policy.patch). Until now this file was vermeer's empty placeholder, so penang
// ran every job: watchdogd with no watchdog backend, the identityservicesd/locationd/CommCenter cycle of synchronous XPC waits,
// fairplayd.A2's KeepAlive loop and adid (with both, SpringBoard does not finish starting on sheng), coreduetd burning a core.
// Explicit temporary bring-up policy for an unavailable watchdog backend.
// Runs after writable scratch Data mounts, before the unchanged launchd exec.
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc.h>
#include <sys/sysproto.h>
#include <sys/fcntl.h>
#include <sys/stat.h>
#include <pexpert/pexpert.h>

// penang has no boot log writer (sheng's BootLog.c boot_log_startup_result, which the kernel link cannot leave unresolved): a failed
// step goes to the console instead.
static int policy_step(const char *stage, int result) {
 if (result) printf("penang launch policy: %s %d\n", stage, result);
 return result;
}
#define POLICY_CALL(stage, expression) (policy_step(stage " enter", 0), policy_step(stage " returned", (expression)))

static const char policy_head[] =
 "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
 "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
 "<plist version=\"1.0\"><dict>";
static const char policy_watchdogd[]="<key>com.apple.watchdogd</key><true/>";
// Bring-up isolation: hardware stacks show identityservicesd, contextstored and locationd in a
// cycle of synchronous XPC waits. A disabled job makes its Mach service lookups fail instead of hang.
// disable-jobs=<label>[,<label>...] (restricted label characters, bounded length).
static const char policy_tail[]="</dict></plist>\n";
// lite=1: jobs that only reach for the network, iCloud or the photo library and have nothing to do on this tablet (no radios, no accounts),
// all of which start at the first boot of a fresh Data and compete with SpringBoard for the CPU and for memory. The first three are the
// cycle of synchronous XPC waits the isolation work found. Labels are the ones in the target's own LaunchDaemons.
static const char lite_jobs[]=
 "com.apple.identityservicesd,com.apple.locationd,com.apple.CommCenter,"
 "com.apple.photoanalysisd,com.apple.mediaanalysisd,com.apple.mediastream.mstreamd,com.apple.icloud.searchpartyd,"
 "com.apple.findmy.findmybeaconingd,com.apple.familycircled,com.apple.financed,com.apple.softwareupdateservicesd,"
 "com.apple.ndoagent,com.apple.biomesyncd,com.apple.email.maild,com.apple.amsengagementd,com.apple.adid,com.apple.eyereliefd,"
 // Crash or respawn loops seen on hardware (int-176): fairplayd.A2 is KeepAlive and exits at once (22 launches in 6 minutes), passd crashes,
 // obliteration is a data-wipe daemon with nothing to do here. iconservicesagent also dies in CI::GLContext::init, but disabling it leaves
 // the icons missing (seen on hardware), so the usual lite policy keeps it enabled. coreduetd keeps one thread above 50 % of a core for the whole boot
 // (the kernel's "burning CPU" report in i480 to i556), holding a big core and the P domain at its top clock.
 "com.apple.fairplayd.A2,com.apple.passd,com.apple.mobile.obliteration,com.apple.coreduetd,"
 // Advice and statistics services with nothing to advise on here (untagged-3f2bd680: PerfPowerServices alone held 1.8 of 7 CPUs while it
 // wrote its power database, BackgroundShortcutRunner 0.3 to 0.5 all boot, duetexpertd 0.17 in Safari). Temporarily disabled to measure.
 "com.apple.PerfPowerServices,com.apple.PerfPowerServicesExtended,com.apple.perfpowermetricd,com.apple.siriinferenced,"
 "com.apple.siriknowledged,com.apple.siriactionsd,com.apple.duetexpertd,com.apple.modelcatalogd";
// penang: sheng's PE_builtin_boot_args is left out (this kernel's pexpert has no built-in argument reader); the board puts
// disable-watchdogd=1 lite=1 and the scheduler hygiene switches on the command line instead.
static char policy[2048],jobs[200],enable_jobs[200];
volatile int sheng_watchdog_policy_status=-1;

// setup=1 or data-reset=2 (the install entry's "show Hello" choice): remove Setup's completion flags once, so this boot shows the Hello page.
// iPadOS writes them again when Setup finishes, so later boots do not show it. Absent files are fine.
static int sheng_boot_setup_reset(proc_t p,uint64_t scratch) {
 static const char *const files[]={
  "/private/var/mobile/Library/Preferences/com.apple.purplebuddy.plist",
  "/private/var/mobile/Library/Preferences/com.apple.purplebuddy.notbackedup.plist"};
 for(unsigned i=0;i<sizeof(files)/sizeof(files[0]);++i) {
  int32_t result=0;
  int error=copyout(files[i],scratch,strlen(files[i])+1);
  if(error)return error;
  struct unlink_args rm={.path=scratch};
  error=unlink(p,&rm,&result);
  if(error && error!=ENOENT)return error;
 }
 return 0;
}

// Append one label with its launchd disabled state and advance past the comma.
static int append_job_state(const char **cursor,int disabled) {
 const char *c=*cursor,*e=c;while(*e && *e!=',')++e;
 if(e>c) {
  if(strlcat(policy,"<key>",sizeof(policy))>=sizeof(policy))return EINVAL;
  size_t at=strlen(policy);if(at+(size_t)(e-c)+1>=sizeof(policy))return EINVAL;
  memcpy(policy+at,c,(size_t)(e-c));policy[at+(size_t)(e-c)]=0;
  if(strlcat(policy,disabled?"</key><true/>":"</key><false/>",sizeof(policy))>=sizeof(policy))return EINVAL;
 }
 *cursor=*e?e+1:e;return 0;
}

static int append_job(const char **cursor) {return append_job_state(cursor,1);}

int sheng_boot_watchdog_policy(void *process, uint64_t scratch) {
 proc_t p=process;
 int enabled=0,error=0,fd=-1;int32_t result=0;
 PE_parse_boot_argn("disable-watchdogd",&enabled,sizeof(enabled));
 if(!PE_parse_boot_argn("disable-jobs",jobs,sizeof(jobs)))jobs[0]=0;jobs[sizeof(jobs)-1]=0;
 if(!PE_parse_boot_argn("enable-jobs",enable_jobs,sizeof(enable_jobs)))enable_jobs[0]=0;enable_jobs[sizeof(enable_jobs)-1]=0;
 int lite=0;PE_parse_boot_argn("lite",&lite,sizeof(lite));if(lite!=1 && lite!=2)lite=0;
 if(enabled!=1)enabled=0;
 for(const char *c=enable_jobs;*c;++c)if(!((*c>='a'&&*c<='z')||(*c>='A'&&*c<='Z')||(*c>='0'&&*c<='9')||*c=='.'||*c=='-'||*c==','))return EINVAL;
 for(const char *c=jobs;*c;++c)if(!((*c>='a'&&*c<='z')||(*c>='A'&&*c<='Z')||(*c>='0'&&*c<='9')||*c=='.'||*c=='-'||*c==','))return EINVAL;
 int setup=0,reset=0;
 PE_parse_boot_argn("setup",&setup,sizeof(setup));
 PE_parse_boot_argn("data-reset",&reset,sizeof(reset));   // 2 = erase Data and show the Hello page; 1 = erase Data, Setup stays skipped
 if(reset==2)setup=1;
 if(setup==1 && (error=sheng_boot_setup_reset(p,scratch))) {
  sheng_watchdog_policy_status=error;
  printf("sheng setup flags reset failed: %d\n",error);
  return error;
 }
 if(setup==1)printf("sheng setup flags reset: Hello page on this boot\n");
 if(!enabled && !jobs[0] && !enable_jobs[0] && !lite)return 0;
 policy[0]=0;strlcat(policy,policy_head,sizeof(policy));
 if(enabled)strlcat(policy,policy_watchdogd,sizeof(policy));
 if(lite)for(const char *c=lite_jobs;*c;) {if((error=append_job(&c)))return error;}
 if(lite==2) {
  const char *icon_agent="com.apple.iconservices.iconservicesagent";
  if((error=append_job(&icon_agent)))return error;
 }
 for(const char *c=jobs;*c;) {if((error=append_job(&c)))return error;}
 for(const char *c=enable_jobs;*c;) {if((error=append_job_state(&c,0)))return error;}
 strlcat(policy,policy_tail,sizeof(policy));
 const char *directory="/private/var/db/com.apple.xpc.launchd";
 const char *path="/private/var/db/com.apple.xpc.launchd/disabled.plist";
 if((error=copyout(directory,scratch,strlen(directory)+1)))goto done;
 struct mkdir_args md={.path=scratch,.mode=0755};
 error=POLICY_CALL("launch policy mkdir", mkdir(p,&md,&result));
 if(error && error!=EEXIST)goto done;
 if((error=copyout(path,scratch,strlen(path)+1)))goto done;
 // With persistent Data the previous boot's file is there: this policy is rewritten in place on every boot (it must follow the
 // boot arguments). Symlinks are still refused (O_NOFOLLOW) and the fstat check below insists on a root-owned regular file.
 struct open_args op={.path=scratch,.flags=O_WRONLY|O_CREAT|O_TRUNC|O_NOFOLLOW,.mode=0644};
 if((error=POLICY_CALL("launch policy open", open(p,&op,&result))))goto done;
 fd=result;
 // The scratch page keeps the cache-mount environment slots at +0x400, so the policy (the lite list makes it longer than 0x200 bytes) goes
 // out in pieces through the 0x200 bytes at +0x200.
 for(size_t sent=0,total=strlen(policy);sent<total;) {
  size_t piece=total-sent<0x1f0?total-sent:0x1f0;
  if((error=copyout(policy+sent,scratch+0x200,piece)))goto done;
  struct write_args wr={.fd=fd,.cbuf=scratch+0x200,.nbyte=piece};
  user_ssize_t written=0;
  if((error=POLICY_CALL("launch policy write", write(p,&wr,&written))))goto done;
  if(written!=(user_ssize_t)piece){error=EIO;goto done;}
  sent+=piece;
 }
 struct fchown_args owner={.fd=fd,.uid=0,.gid=0};
 if((error=POLICY_CALL("launch policy chown", fchown(p,&owner,&result))))goto done;
 struct fchmod_args mode={.fd=fd,.mode=0644};
 if((error=POLICY_CALL("launch policy chmod", fchmod(p,&mode,&result))))goto done;
 struct fsync_args sync={.fd=fd};
 if((error=POLICY_CALL("launch policy fsync", fsync(p,&sync,&result))))goto done;
 // Preserve the cache-mount environment slots at +0x400, +0x500, +0x600.
 struct fstat64_args sa={.fd=fd,.ub=scratch+0x800};struct stat64 st={0};
 if((error=POLICY_CALL("launch policy stat", sys_fstat64(p,&sa,&result))) || (error=copyin(sa.ub,&st,sizeof(st))))goto done;
 if(st.st_uid!=0 || st.st_gid!=0 || !S_ISREG(st.st_mode) || (st.st_mode&0777)!=0644 || st.st_size!=(off_t)(strlen(policy)))error=EINVAL;
 done:
 if(fd>=0){struct close_args cl={.fd=fd};int e=POLICY_CALL("launch policy close", sys_close(p,&cl,&result));if(!error)error=e;}
 // A real empty migration marker selects the qualified modern override loader.
 if(!error) {
  const char *marker="/private/var/db/com.apple.xpc.launchd/disabled.migrated";
  error=copyout(marker,scratch,strlen(marker)+1);
  if(!error) {
   struct open_args mark={.path=scratch,.flags=O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,.mode=0644};
   error=POLICY_CALL("launch policy marker open", open(p,&mark,&result));
   if(!error){struct close_args cl={.fd=result};error=POLICY_CALL("launch policy close", sys_close(p,&cl,&result));}
   else if(error==EEXIST)error=0;
  }
 }
 sheng_watchdog_policy_status=error;
 if(lite==2 && !error)printf("sheng launch policy: disabled com.apple.iconservices.iconservicesagent\n");
 printf("sheng bring-up watchdogd launch policy: %d (hardware watchdog not implemented)\n",error);
 return error;
}
