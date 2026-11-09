"""Shared Neo4j connection for all graph scripts."""

import os

import certifi
from dotenv import load_dotenv
from neo4j import GraphDatabase, TrustCustomCAs

load_dotenv()

def get_driver():
    # neo4j+s:// does not allow custom certificate settings, so use neo4j://
    # and switch encryption on ourselves (still encrypted and verified)
    uri = os.environ["NEO4J_URI"].replace("neo4j+s://", "neo4j://")
    auth = (os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
    return GraphDatabase.driver(
        uri,
        auth=auth,
        encrypted=True,
        trusted_certificates=TrustCustomCAs(certifi.where()),  # certifi's list of trusted signers
    )

