#!/usr/bin/python3

import argparse
import timeit

import sys
print(2)
print(sys.version)

import pandas as pd
import string
from nltk.corpus import stopwords
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from datasketch import MinHash, MinHashLSHForest

def main():
    ###  Number of similar songs
    numOfSimSongs = 5
    outputFile = 'similarsongs.csv'

    numOfSimSongs, outputFile = getArguments(numOfSimSongs, outputFile)

    ### Reading data
    print("Loading the Data File")
    songsDataFrame = pd.read_csv('songsData.csv', sep=',')
    print("Finished Loading the Data File\n")

    ### If you want to add the title of the song in the process
    songsDataFrame = songsDataFrame['song'].str.cat(songsDataFrame['text'], sep=" ")

    ### adding the song's lyrics only
    # songsDataFrame = songsDataFrame['text']

    ### Converting the data frame into array list for better and easier handling
    songsList = songsDataFrame.values.tolist()

    ### simSongList had the ID and the number of similar songs (Building the data frame)
    similarSongHeader = ['ID']
    for i in range(numOfSimSongs):
        similarSongHeader.append("song" + str(i + 1))

    print("Data Cleaning")
    start_time = timeit.default_timer()
    cleanSongList = toCleanData(songsList)
    print("Data Cleaning took %s seconds ---" % (timeit.default_timer() - start_time))

    print("Building LSH")
    start_time = timeit.default_timer()
    forestLSH, minHashList = toBuildLSH(cleanSongList)
    print("Building LSH took %s seconds ---" % (timeit.default_timer() - start_time))

    print("Querying the similar songs")
    similarSongsIdList = toQuerySimilarSongs(forestLSH, minHashList, numOfSimSongs)
    print("Querying took %s seconds ---" % (timeit.default_timer() - start_time))

    print("Saving results to the file: %s" % outputFile)
    ### saving the result in a dataframe shape
    results_df = pd.DataFrame(similarSongsIdList, columns=similarSongHeader)
    ### writing the dataframe onto the file named in the variable simFile
    results_df.to_csv(outputFile, sep=',', encoding='utf-8')
    print("Finished saving the results \n")

    
### cleaning function to tokenize, remove stopwords
def toCleanData(songsList):
    '''
    :param songsList
    :return: clean_song_list
    '''
    clean_song_list = []
    ### groups of stop words (nltk and scikit-learn)
    nltk_stop_words_list = stopwords.words('english')
    nltk_stop_words_list += ENGLISH_STOP_WORDS
    for songIndex, song in enumerate(songsList):
        ### convert to lower case text and replace the punctuation ' with space (clearer words to be categorized with LSH)
        song_lower_case = song.lower().replace("'", ' ')
        ### remove punctuation and tokenize the song into words (can use NLTK word_tokenize but words like wanna will be "wan" "na")
        tokens = (song_lower_case.translate(str.maketrans('', '', string.punctuation))).split()
        clean_song = [word for word in tokens if word.strip() not in nltk_stop_words_list and len(word) > 2]
        ### defining the MinHash for each song

        clean_song_list.append(clean_song)
    return clean_song_list


def toBuildLSH(cleanSongs):
    '''
    :param cleanSongs
    :return: forest, min_hash_list
    '''
    forest = MinHashLSHForest(num_perm=128)
    min_hash_list = []
    for songIndex, song in enumerate(cleanSongs):
        minhash = MinHash(num_perm=128)
        for word in song:
            ### encoding each word
            minhash.update(word.encode('utf8'))
        ### add each song's minhash to the forest as well as min_hash_list
        forest.add(str(songIndex), minhash)
        min_hash_list.append(minhash)

    forest.index()
    return forest, min_hash_list


def toQuerySimilarSongs(forestLSH, minHashList, numOfSimSongs):
    '''
    :param: forestLSH, minHashList, numOfSimSongs
    :return: similar_songs_list
    '''
    similar_songs_list = []
    for minHashIndex, minHash in enumerate(minHashList):
        ### query numOfSimSongs + 1 as most of results will return the same song ID
        result = forestLSH.query(minHash, numOfSimSongs + 1)
        try:
            result.remove(str(minHashIndex))
            result.insert(0, minHashIndex)
        except:
            ### If the output result does not have the song itself
            if len(result) > 0:
                result.remove(result[0])
            result.insert(0, minHashIndex)

        similar_songs_list.append(result)

        #### If you want to figure out the song's ID which has lass than number of similar songs
        # if len(result) < numOfSimSongs:
        #     print("This song has less than %s of similar songs: " % numOfSimSongs, minHashIndex)
    return similar_songs_list


def getArguments(numOfSimSongs, outputFile):
    '''
    :param: numOfSimSongs, outputFile
    :return: numOfSimSongs, outputFile
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument("--simsongs", type=int,
                        help="Number of similar songs to be found, the default is 5 songs ")
    parser.add_argument("--output", type=str,
                        help="The name of the output file, the default is 'similarsongs.csv'")
    args = parser.parse_args()
    if args.simsongs != None:
        numOfSimSongs = args.simsongs
    if args.output != None:
        outputFile = args.output

    return numOfSimSongs, outputFile

if __name__ == '__main__':
    main()
