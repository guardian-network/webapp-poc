#!/usr/bin/env python3

# std lib
from subprocess import Popen, PIPE, DEVNULL
import shlex
import time
import os
import shutil
import glob
import tempfile

# Third party lib
from termcolor import colored

# In house Lib
from src.lib.settings import Settings
from utils import snps_match, compare_pca, compare_regression


def process_finished(message):
    if message.startswith("Looks") or message.startswith("Indicate"):
        return True
    return False


def wait_for_process_to_finish(server):
    message = server.stdout.readline()
    while not process_finished(message):
        if message != '':
            print(message)
        message = server.stdout.readline()


def wait_for_client_to_finish(client, k):
    client.stdout.flush()
    for line in client.stdout.readline():
        print(line)
        k -= 1
        client.stdout.flush()


def startup_server_client(scratch=None, PORT=" 9000"):
    if scratch is None:
        scratch = Settings.local_scratch
    server = Popen(shlex.split(Settings.python + " server.py " + scratch + PORT), stdin=PIPE, 
        stdout=PIPE, bufsize=1, universal_newlines=True)
    client = Popen(shlex.split(Settings.python + " runner.py " + scratch + PORT),
        bufsize=1, stdout=PIPE, stderr=DEVNULL, universal_newlines=True)
    message = server.stdout.readline()
    wait_for_process_to_finish(server)
    return server, client


def copy_datasets(location):
    files_to_copy = glob.iglob(os.path.join(Settings.local_scratch, '*.h5py'))
    for f in files_to_copy:
        shutil.copy(f, location)


def test_init():
    server, client = startup_server_client()
    server.stdin.write('init\n')
    print("initalized!")
    wait_for_process_to_finish(server)
    time.sleep(1)
    server.stdin.write('exit\n')
    server.stdin.close()
    return snps_match('testData/subsampled', Settings.local_scratch+'/testDatadset1.h5py')


def run_plink(plink_cmd, inPlink, temp_fldr):
    outname = os.path.join(temp_fldr, os.path.basename(inPlink))
    full_cmd = "{plink} --bfile {plink_file} {cmd} --out {outname}".format(
        plink=Settings.plink, plink_file=inPlink, cmd=plink_cmd, outname=outname)
    print("Running plink command")
    plink_running = Popen(shlex.split(full_cmd), stdin=PIPE, stdout=PIPE)
    plink_running.wait()


def qc_setup(cmd='QC', local_scratch=None):
    if local_scratch is None:
        local_scratch = Settings.local_scratch
    temp_location = tempfile.mkdtemp(prefix=local_scratch+"/")
    copy_datasets(temp_location)
    server, client = startup_server_client(temp_location)
    server.stdin.write('{}\n'.format(cmd))
    return temp_location, server, client


def test_qc_hwe(threshold):
    temp_location, server, client = qc_setup()
    server.stdin.write('hwe {}\n'.format(threshold))
    wait_for_process_to_finish(server)
    plink_cmd = "--hwe {} midp keep-fewhet --make-bed".format(threshold)
    run_plink(plink_cmd, 'testData/subsampled', temp_location)
    server.stdin.write('exit\n')
    server.stdin.close()
    plink_to_compare_to = os.path.join(temp_location, 'subsampled')
    time.sleep(1)
    results = snps_match(plink_to_compare_to, temp_location+'/central.h5py')
    shutil.rmtree(temp_location)
    return results


def test_qc_maf(threshold):
    temp_location, server, client = qc_setup()
    server.stdin.write('maf {}\n'.format(threshold))
    wait_for_process_to_finish(server)
    plink_cmd = "--maf {} --make-bed".format(threshold)
    run_plink(plink_cmd, 'testData/subsampled', temp_location)
    server.stdin.write('exit\n')
    server.stdin.close()
    time.sleep(1)
    plink_to_compare_to = os.path.join(temp_location, 'subsampled')
    results = snps_match(plink_to_compare_to, temp_location+'/central.h5py')
    shutil.rmtree(temp_location)
    return results


def test_qc_mps(threshold):
    temp_location, server, client = qc_setup()
    server.stdin.write('mps {}\n'.format(threshold))
    wait_for_process_to_finish(server)
    plink_cmd = "--geno {} --make-bed".format(threshold)
    run_plink(plink_cmd, 'testData/subsampled', temp_location)
    server.stdin.write('exit\n')
    server.stdin.close()
    time.sleep(.1)
    plink_to_compare_to = os.path.join(temp_location, 'subsampled')
    results = snps_match(plink_to_compare_to, temp_location+'/central.h5py')
    shutil.rmtree(temp_location)
    return results


##### PCA TESTS


def test_pca_ld_pruning(win, num_pcs):
    temp_location, server, client = qc_setup('pca')
    server.stdin.write('maf 0.1 hwe 1e-5 ld {}\n'.format(win))
    wait_for_process_to_finish(server)
    time.sleep(1)
    server.stdin.write('exit')
    server.stdin.close()
    client.terminate()
    plink_cmd = "--maf 0.1 --hwe 1e-5 midp --indep-pairwise {} 25 0.2".format(win)
    run_plink(plink_cmd, 'testData/subsampled', temp_location)
    plink_cmd = "--extract {}/subsampled.prune.in --make-bed".format(
        temp_location)
    run_plink(plink_cmd, 'testData/subsampled', temp_location)
    plink_to_compare_to = os.path.join(temp_location, 'subsampled')
    ld_results = snps_match(plink_to_compare_to, temp_location+'/central.h5py', 
        'PCA_positions')
    ## Now we check theactual pcs
    plink_cmd = "--pca {}".format(num_pcs)
    plink_loc = temp_location+'/subsampled'
    run_plink(plink_cmd, temp_location+'/subsampled', temp_location)
    dsets = [temp_location+'/testDatadset1.h5py', temp_location+'/testDatadset2.h5py', 
        temp_location+'/testDatadset3.h5py']
    time.sleep(1)
    pca_results = compare_pca(plink_loc, temp_location+'/central.h5py', dsets)
    return ld_results, pca_results, temp_location


##### ASSOCIATION TESTS

def test_ass(ncov, temp_dir):
    server, client = startup_server_client(scratch=temp_dir, PORT=' 9002')
    time.sleep(1)
    server.stdin.write('Asso\n')
    time.sleep(.1)
    server.stdin.write('{}\n'.format(0)) # 10 pcs
    wait_for_process_to_finish(server)
    server.stdin.write('exit')
    server.stdin.close()
    plinkName = 'testData/subsampled'
#    plink_cmd = "--pheno {} --logistic beta --allow-no-sex --covar {}".format(
#        plinkName+'.pheno', temp_dir+"/subsampled.eigenvec")
    pdb.set_trace()
    plink_cmd = "--pheno {} --logistic beta --allow-no-sex".format(
        plinkName+'.pheno')
    run_plink(plink_cmd, 'testData/subsampled', temp_dir)
    time.sleep(10)
    compare_regression(temp_dir+"/subsampled.assoc.logistic", temp_dir+'/central.h5py')


def run_tests():
    assert test_init(), "Initialization failed"
    #print(colored("Initialization test: ",'red'), colored(u'\u2713', 'red'))
    #assert test_qc_hwe(1e-5), "HWE failed"
    #print(colored("QC HWE test: ",'red'), colored(u'\u2713', 'red'))
    #assert test_qc_maf(0.1), "MAF failed"
    #print(colored("QC maf test: ",'red'), colored(u'\u2713', 'red'))
    #assert test_qc_mps(0.05), "Missing per snp failed"
    #print(colored("QC missing per snp test: ",'red'), colored(u'\u2713', 'red'))
    ld_results, pca_results, pca_temp_location = test_pca_ld_pruning(50, 4)
    assert ld_results, "LD pruning failed"
    print(colored("LD pruning test: ",'red'), colored(u'\u2713', 'red'))
    #assert pca_results, "PCA failed"
    #print(colored("PCA pruning test: ",'red'), colored(u'\u2713', 'red'))
    #test_ass(4, pca_temp_location)


def main():
    run_tests()


if __name__ == '__main__':
    main()

