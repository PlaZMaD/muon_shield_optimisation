#!/usr/bin/env python2
import os
import random
import tempfile
import numexpr as ne
from multiprocessing import Pipe
from multiprocessing import Process
from multiprocessing import cpu_count
from multiprocessing import current_process
import argparse
import numpy as np
import ROOT as r
import shipunit as u
from ShipGeoConfig import ConfigRegistry
import shipDet_conf
from slave import generate


def magnetMass(muonShield):
    """Calculate magnet weight [kg]

    Assumes magnets contained in `MuonShieldArea` TGeoVolumeAssembly and
    contain `Magn` in their name. Calculation is done analytically by
    the TGeoVolume class.

    """
    nodes = muonShield.GetNodes()
    m = 0.
    for node in nodes:
        volume = node.GetVolume()
        if 'Magn' in volume.GetName():
            m += volume.Weight(0.01, 'a')
    return m


def magnetLength(muonShield):
    """Ask TGeoShapeAssembly for magnet length [cm]

    Note: Ignores one of the gaps before or after the magnet

    Also note: TGeoShapeAssembly::GetDZ() returns a half-length

    """
    length = 2 * muonShield.GetShape().GetDZ()
    return length


def FCN(W, x, L):
    """Calculate penalty function.

    W = weight [kg]
    x = array of positions of muon hits in bending plane [cm]
    L = shield length [cm]

    """
    Sxi2 = ne.evaluate('sum(sqrt(560-(x+300.)/560))') if x else 0.
    print W, x, L, Sxi2
    return ne.evaluate('0.01*(W/1000)*(1.+Sxi2/(1.-L/10000.))')


def worker(master):
    # TODO migrate to slave.py
    id_ = master.recv()
    ego = current_process()
    worker_filename = '{}_{}.root'.format(id_, args.njobs)
    n = (ntotal / args.njobs)
    firstEvent = n * (id_ - 1)
    n += (ntotal % args.njobs if id_ == args.njobs else 0)
    print id_, ego.pid, 'Produce', n, 'events starting with event', firstEvent
    n = 100
    if os.path.isfile(worker_filename):
        print worker_filename, 'exists.'
    else:
        f = r.TFile.Open(args.input)
        tree = f.Get('pythia8-Geant4')
        worker_file = r.TFile.Open(worker_filename, 'recreate')
        worker_data = tree.CopyTree('', '', n, firstEvent)
        worker_data.Write()
        worker_file.Close()
    # Output file name, add dy to be able to setup geometry with ambiguities.
    tag = simEngine + '-' + mcEngine
    tag = 'conical.' + tag
    if not os.path.exists(outputDir):
        os.makedirs(outputDir)

    outFile = '{}/{}.ship.{}.root'.format(outputDir, ego.pid, tag)
    # TODO read geometry from queue after each iteration
    while True:
        geoFile = master.recv()
        if not geoFile:
            break
        p = Process(
            target=generate, args=(worker_filename, geoFile, n, outFile))
        p.start()
        p.join()
        ch = r.TChain('cbmsim')
        ch.Add(outFile)
        xs = []
        mom = r.TVector3()
        for event in ch:
            weight = event.MCTrack[1].GetWeight()
            if weight == 0:
                weight = 1.
            for hit in event.strawtubesPoint:
                if hit:
                    if not hit.GetEnergyLoss() > 0:
                        continue
                    if hit.GetDetectorID() / 10000000 == 4 and abs(hit.PdgCode(
                    )) == 13:
                        hit.Momentum(mom)
                        P = mom.Mag() / u.GeV
                        if P > 1:
                            y = hit.GetY()
                            if abs(y) < 5 * u.m:
                                x = hit.GetX()
                                if x < 2.6 * u.m and x > -3 * u.m:
                                    xs.append(x)
        master.send(xs)
        os.remove(outFile)
    print 'Worker process {} done.'.format(id_)


def get_geo(geoFile, out):
    ship_geo = ConfigRegistry.loadpy(
        '$FAIRSHIP/geometry/geometry_config.py',
        Yheight=dy,
        tankDesign=vessel_design,
        muShieldDesign=shield_design,
        muShieldGeo=geoFile)

    with tempfile.NamedTemporaryFile() as t:
        run = r.FairRunSim()
        run.SetName('TGeant4')  # Transport engine
        run.SetOutputFile(t.name)  # Output file
        run.SetUserConfig('g4Config.C')
        shipDet_conf.configure(run, ship_geo)
        run.Init()
        run.CreateGeometryFile('./geo/' + os.path.basename(geoFile))
        sGeo = r.gGeoManager
        muonShield = sGeo.GetVolume('MuonShieldArea')
        L = magnetLength(muonShield)
        W = magnetMass(muonShield)
    out.send((L, W))


def geo_guessr():
    dZgap = 0.1 * u.m
    zGap = 0.5 * dZgap  # halflengh of gap
    dZ1 = 0.7 * u.m
    dZ2 = 1.7 * u.m
    dZ3 = 0.2 * u.m + 3. * random.random() * u.m + zGap
    dZ4 = 0.2 * u.m + 3. * random.random() * u.m + zGap
    dZ5 = 0.2 * u.m + 3. * random.random() * u.m + zGap
    dZ6 = 0.2 * u.m + 3. * random.random() * u.m + zGap
    dZ7 = 0.2 * u.m + 3. * random.random() * u.m + zGap
    dZ8 = 0.2 * u.m + 3. * random.random() * u.m + zGap
    params = [dZ1, dZ2, dZ3, dZ4, dZ5, dZ6, dZ7, dZ8]
    for _ in range(8):
        minimum = 0.1 * u.m
        dXIn = minimum + 2.4 * random.random() * u.m
        dXOut = minimum + 2.4 * random.random() * u.m
        dYIn = minimum + 2.4 * random.random() * u.m
        dYOut = minimum + 2.4 * random.random() * u.m
        assert dXIn + dYIn <= 5. * u.m
        assert dXOut + dYOut <= 5. * u.m
        gapIn = 2. + 4.98 * random.random() * u.m
        gapOut = 2. + 4.98 * random.random() * u.m
        assert 2 * dXIn + gapIn <= 10. * u.m
        assert 2 * dXOut + gapOut <= 10. * u.m
        params += [dXIn, dXOut, dYIn, dYOut, gapIn, gapOut]
    return params


def generate_geo(geofile, params):
    f = r.TFile.Open(geofile, 'recreate')
    parray = r.TVectorD(len(params), np.array(params))
    parray.Write('params')
    f.Close()
    return geofile


def main():
    pipes = [Pipe(duplex=True) for _ in range(args.njobs)]
    ps = [(w, Process(target=worker, args=[m])) for m, w in pipes]
    for i, p in enumerate(ps):
        p[1].start()
        p[0].send(i + 1)

    counter = 0
    for _ in range(1):
        params = geo_guessr()
        counter += 1
        geoFile = generate_geo('geo_{}.root'.format(counter), params)
        out_, in_ = Pipe(duplex=False)
        geo_process = Process(target=get_geo, args=[geoFile, in_])
        geo_process.start()
        L, W = out_.recv()
        for w, _ in ps:
            w.send(geoFile)
        xss = [w.recv() for w, _ in ps]
        xs = [x for xs_ in xss for x in xs_]
        fcn = FCN(W, np.array(xs), L)
        assert np.isclose(
            L / 2., sum(params[:8]) + 5
        ), 'Analytical and ROOT lengths are not the same.'
        print fcn
    for w, _ in ps:
        w.send(False)


if __name__ == '__main__':
    r.gErrorIgnoreLevel = r.kWarning
    r.gSystem.Load('libpythia8')
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-f',
        '--input',
        default='root://eoslhcb.cern.ch/'
        '/eos/ship/data/Mbias/'
        'pythia8_Geant4-withCharm_onlyMuons_4magTarget.root'
    )
    parser.add_argument(
        '-n',
        '--njobs',
        type=int,
        default=min(8, cpu_count()), )
    args = parser.parse_args()
    # ntotal = 17786274
    ntotal = 86229
    # TODO read total number from muon file directly
    dy = 10.
    vessel_design = 5
    shield_design = 8
    mcEngine = 'TGeant4'
    simEngine = 'MuonBack'
    outputDir = '.'
    sameSeed = 1
    theSeed = 1
    main()
