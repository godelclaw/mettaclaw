import os
import sys
sys.path.insert(0, os.path.expanduser('~/repos/mettaclaw'))
from ggb_bridge_ext import ggbL3Share, ggbL3Query, ggbL3Revise

def share(agent, content, key, strength, confidence, goal, timestamp, origin):
    return ggbL3Share(agent, content, key, strength, confidence, goal, timestamp, origin)

def query(query_str, limit=5):
    return ggbL3Query(query_str, limit)

def revise(agent):
    return ggbL3Revise(agent)