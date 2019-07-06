# Author: Parag Mali
# This script stitches back the output generated on the image patches (sub-images)

# read the image
import sys
sys.path.extend(['/home/psm2208/code', '/home/psm2208/code'])
import cv2
import os
import csv
import numpy as np
import utils.visualize as visualize
from multiprocessing import Pool
from cv2.dnn import NMSBoxes
from scipy.ndimage.measurements import label
import scipy.ndimage as ndimage
import copy
from gtdb import fit_box
from gtdb import box_utils
from gtdb import feature_extractor
import shutil
import random
import time

# Default parameters for thr GTDB dataset
intermediate_width = 4800
intermediate_height = 6000
crop_size = 1200

final_width = -1
final_height = -1 # because initial image size is 300 * 300 even for 512 * 512 network

if_visualize = -1
projections = -1

stride = 0.1

n_horizontal = int(intermediate_width / crop_size)  # 4
n_vertical = int(intermediate_height / crop_size)  # 5
algorithm = 'equal'

def read_math_regions(args):

    image, pdf_name, page_num, math_files_list = args

    original_width = image.shape[1]
    original_height = image.shape[0]

    intermediate_width_ratio = original_width / intermediate_width
    intermediate_height_ratio = original_height / intermediate_height

    annotations_map = {}

    for math_file in math_files_list:

        name = math_file.split(os.sep)[-1]

        if os.stat(math_file).st_size == 0:
            continue

        data = np.genfromtxt(math_file, delimiter=',')

        # if there is only one entry convert it to correct form required
        if len(data.shape) == 1:
            data = data.reshape(1, -1)

        annotations_map[name] = data


    h = np.arange(0, n_horizontal - 1 + stride, stride)
    v = np.arange(0, n_vertical - 1 + stride, stride)

    for filename in annotations_map:

        data_arr = annotations_map[filename]
        patch_num = int(filename.split("_")[-1].split(".csv")[0])

        x_offset = h[(patch_num - 1) % len(h)]
        y_offset = v[int((patch_num - 1) / len(h))]

        if data_arr is None:
            continue

        # find scaling factors
        final_width_ratio = crop_size / final_width
        final_height_ratio = crop_size / final_height

        data_arr[:, 0] = data_arr[:, 0] * final_width_ratio
        data_arr[:, 2] = data_arr[:, 2] * final_width_ratio
        data_arr[:, 1] = data_arr[:, 1] * final_height_ratio
        data_arr[:, 3] = data_arr[:, 3] * final_height_ratio

        data_arr[:, 0] = data_arr[:, 0] + x_offset * crop_size
        data_arr[:, 2] = data_arr[:, 2] + x_offset * crop_size
        data_arr[:, 1] = data_arr[:, 1] + y_offset * crop_size
        data_arr[:, 3] = data_arr[:, 3] + y_offset * crop_size

        data_arr[:, 0] = data_arr[:, 0] * intermediate_width_ratio
        data_arr[:, 2] = data_arr[:, 2] * intermediate_width_ratio
        data_arr[:, 1] = data_arr[:, 1] * intermediate_height_ratio
        data_arr[:, 3] = data_arr[:, 3] * intermediate_height_ratio

        # multiply score by 100. Because later we convert data_arr to int datatype
        data_arr[:, 4] = data_arr[:, 4] * 100

        annotations_map[filename] = data_arr

    math_regions = np.array([])

    for key in annotations_map:

        if len(math_regions) == 0:
            math_regions = annotations_map[key][:, :]
        else:
            math_regions = np.concatenate((math_regions, annotations_map[key]), axis=0)

    math_regions = math_regions.astype(int)
    math_regions = math_regions[math_regions[:, 4].argsort()]

    return math_regions

def read_char_data(char_filepath):

    # Read char data
    if char_filepath != "":
        char_data = np.genfromtxt(char_filepath, delimiter=',')
        char_data = char_data[:, 2:6]

        # if there is only one entry convert it to correct form required
        if len(char_data.shape) == 1:
            char_data = char_data.reshape(1, -1)

    else:
        char_data = []

    return char_data

def read_gt_regions(gt_dir, pdf_name, page_num):

    gt_regions = None

    if os.path.isfile(os.path.join(gt_dir, pdf_name, page_num + ".pmath")):
        gt_path = os.path.join(gt_dir, pdf_name, page_num + ".pmath")

        try:
            gt_regions = np.genfromtxt(gt_path, delimiter=',')
            gt_regions = gt_regions.astype(int)

            # if there is only one entry convert it to correct form required
            if len(gt_regions.shape) == 1:
                gt_regions = gt_regions.reshape(1, -1)

            gt_regions = gt_regions.tolist()

        except:
            gt_regions = None


def combine_math_regions(args):

    """
    It is called for each page in the pdf
    :param math_files_list:
    :param image_path:
    :param output_image:
    :return:
    """
    pdf_name, page_num, math_files_list, char_filepath, image_path, output_image, \
    gt_dir, thresh, output_dir, alpha, beta, gamma = args

    try:
        image = cv2.imread(image_path)

        math_regions = read_math_regions((image, pdf_name, page_num, math_files_list))
        char_data = read_char_data(char_filepath)

        # intital math regions
        math_regions_initial = np.copy(math_regions)

        #math_regions = preprocess_math_regions(math_regions, image)

        #pp_math_file = open(os.path.join(os.path.dirname(os.path.dirname(math_files_list[0])), page_num + '.ppm'), 'w')
        #writer = csv.writer(pp_math_file, delimiter=",")

        #for math_region in math_regions:
        #   writer.writerow(math_region)

        processed_math_regions = np.copy(math_regions)

        #math_regions = perform_nms(math_regions)
        #math_regions = overlap_expand(math_regions)
        #math_regions = math_regions.tolist()

        # This will give final math regions
        math_regions = voting_algo(math_regions, char_data, image, pdf_name, page_num,
                                   output_dir, alpha, beta, gamma, algorithm=algorithm, thresh_votes=thresh)

        #print('Number of math regions found ', len(math_regions))
        gt_regions = read_gt_regions(gt_dir, pdf_name, page_num)

        if if_visualize == 1:
            visualize.draw_all_boxes(image, processed_math_regions, math_regions, gt_regions, output_image)

        # print('saved ', output_image)
        # visualize.draw_boxes_cv(image, math_regions, gt_regions, output_image)
        # Following works only with 'none' stitching method
        # Can't use any stitching method with this function
        #visualize.draw_stitched_boxes(image, math_regions, output_image)

    except:
        print("Exception while processing ", pdf_name, " ", page_num, " ", sys.exc_info())

    return math_regions

def preprocess_math_regions(math_regions, image):

    im_bw = convert_to_binary(image)

    args = []

    for box in math_regions:
        args.append((im_bw, box))
        #preprocessed_math_regions.append(box)

    pool = Pool(processes=1)
    preprocessed_math_regions = pool.map(fit_box.adjust_box_p, args)
    pool.close()
    pool.join()

    return preprocessed_math_regions


def fusion(args):

    pdf_name, page_num, output_dir, inter_math, math_cache, alpha, beta, gamma = args

    #equal_votes = voting_equal(votes, math_regions)
    math_regions = np.copy(math_cache)

    # get rid of all boxes which are less than alpha confident
    #math_regions = math_regions[math_regions[:,-1]>(alpha*100)]

    #inter_math = box_utils.find_intersecting_boxes(math_regions)

#    math_regions = math_regions.tolist()
    final_math = []
    removed = set(np.argwhere(math_regions[:,-1]<(alpha*100)).flatten())

    for key in inter_math:

        if key not in removed:
            box1 = math_regions[key]

            for v in inter_math[key]:
                if v not in removed:
                    box2 = math_regions[v]

                    # if IOU > beta, merge
                    if feature_extractor.iou(box1, box2) > beta:
                        box1 = box_utils.merge(box1, box2)
                        removed.add(v)

                    # if inclusion > gamma, remove
                    elif feature_extractor.inclusion(box1, box2) > gamma:
                        removed.add(key)
                    elif feature_extractor.inclusion(box2, box1) > gamma:
                        removed.add(v)

    op_dir = os.path.join(output_dir, 'fusion_' + str("{:.1f}".format(alpha)) + '_' +
                          str("{:.1f}".format(beta)) + '_' + str("{:.1f}".format(gamma)))

    if not os.path.exists(op_dir):
        os.mkdir(op_dir)

    math_file = open(os.path.join(op_dir, pdf_name + '.csv'), 'a')
    #writer = csv.writer(math_file, delimiter=",")

    count = 0
    keep = []

    for math_region in math_regions:
        if count not in removed:
            keep.append(True)
        else:
            keep.append(False)
        count = count + 1

    math_regions = math_regions[keep]
    #col = np.full((1, math_regions.shape[0]), )

    col = np.array([int(page_num) - 1] * math_regions.shape[0])
    math_regions = np.concatenate((col[:, np.newaxis], math_regions), axis=1)

    np.savetxt(math_file, math_regions, delimiter=',')

    return final_math


def voting_equal(votes, math_regions):
    # cast votes for the regions
    for box in math_regions:
        votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = \
            votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] + 1

    return votes

def voting_avg_score(votes, math_regions):

    counts = np.zeros(shape=votes.shape)

    # cast votes for the regions
    for box in math_regions:
        votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = \
            votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] + box[4]

    # count the regions
    for box in math_regions:
        counts[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = \
            counts[int(box[1]):int(box[3]), int(box[0]):int(box[2])] + 1

    # To avoid divide by zero
    # When counts is zero, votes will be zero
    # So this should not affect the calculations and results
    counts[counts == 0] = 1

    votes = votes / counts

    return votes

def voting_sum_score(votes, math_regions):

    # cast votes for the regions
    for box in math_regions:
        votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = \
            votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] + box[4]

    return votes


# def voting_sum_score(votes, boundary_scores, math_regions):
#
#     # cast votes for the regions
#     for box in math_regions:
#         votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = \
#             votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] + box[4]
#
#         boundary_scores[int(box[1]), int(box[0]):int(box[2])] = \
#              boundary_scores[int(box[1]), int(box[0]):int(box[2])] + box[4]
#         boundary_scores[int(box[3]), int(box[0]):int(box[2])] = \
#              boundary_scores[int(box[3]), int(box[0]):int(box[2])] + box[4]
#
#     return votes, boundary_scores

def voting_heuristic_score(votes, math_regions):

    # All the connected components should have equal score

    # Threshold on the score

    # Threshold on the votes
    pass

def voting_max_score(votes, math_regions):

    # sort based on the confs. Confs is column 4
    data = math_regions[math_regions[:, 4].argsort()]

    for box in data:
        votes[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = box[4]

    return votes

def vote_for_regions(math_regions, image, algorithm, thresh_votes):

    original_width = image.shape[1]
    original_height = image.shape[0]

    votes = np.zeros(shape=(original_height, original_width))
    #boundary_scores = np.zeros(shape=(original_height, original_width))

    if algorithm == 'sum_score':
        thresh_votes = thresh_votes * 100
        votes = voting_sum_score(votes, math_regions)
    elif algorithm == 'max_score':
        votes = voting_max_score(votes, math_regions)
    elif algorithm == 'avg_score':
        thresh_votes = thresh_votes * 100
        votes = voting_avg_score(votes, math_regions)
    else:  # algorithm='equal'
        votes = voting_equal(votes, math_regions)

    #cv2.imwrite('/home/psm2208/votes.png', votes*255/np.max(votes))

    # find the regions with higher than the threshold votes
    # change all the values less than thresh_votes to 0
    votes[votes < thresh_votes] = 0
    votes[votes >= thresh_votes] = 1

    #cv2.imwrite('/home/psm2208/votes_bw.png', votes*255)

    return votes

def label_regions(math_regions, image):
    labeled = np.zeros(image.shape[:2])

    math_regions = math_regions[math_regions[:, 4].argsort()]

    for label, math_region in enumerate(math_regions):
        labeled[math_region[1]:math_region[3], math_region[0]:math_region[2]] = label

    #uniq_labels = np.unique(labeled)

    return labeled

def area(box):

    w = box[3] - box[1]
    h = box[2] - box[0]

    return w*h

def char_algo(math_regions, char_data, image, algorithm='equal', thresh_votes=20):

    if len(char_data) == 0:
        return []

    # vote for the regions
    votes = vote_for_regions(math_regions, image, algorithm, thresh_votes)

    # Check if character is math or not
    char_data = char_data.tolist()

    for char_box in char_data:
        #print('nz ', np.count_nonzero(votes[int(char_box[1]):int(char_box[3]), int(char_box[0]):int(char_box[2])]))

        if np.count_nonzero(votes[int(char_box[1]):int(char_box[3]), int(char_box[0]):int(char_box[2])]) > 100:
            char_box.append(1) # APPEND 1 to indicate that it is a math character
        else:
            char_box.append(0)

    # TODO Find the regions

    boxes = []

    box = []

    for char_box in char_data:

        if char_box[-1] == 1:
            if len(box) == 0:
                box = copy.deepcopy(char_box[:4])
                continue

            nbox = copy.deepcopy(box)
            nbox[0] = min(char_box[0], box[0])  # left
            nbox[1] = min(char_box[1], box[1])  # top
            nbox[2] = max(char_box[2], box[2])  # left + width
            nbox[3] = max(char_box[3], box[3])  # top + height

            if area(nbox) > 4 * area(box):
                boxes.append(box)
                box = copy.deepcopy(char_box[:4])
            else:
                box = nbox
        else:
            if len(box) != 0:
                boxes.append(box)
                box = []

    if len(box) != 0:
        boxes.append(box)

    return boxes


def voting_algo(math_regions, char_data, image, pdf_name, page_num,
                output_dir, alpha, beta, gamma, algorithm='equal', thresh_votes=20):

    if algorithm == 'char_algo':
        return char_algo(math_regions, char_data, image, algorithm, thresh_votes)

    elif algorithm == 'fusion':
        fusion(copy.deepcopy(math_regions), pdf_name, page_num, output_dir, alpha=alpha, beta=beta, gamma=gamma)
        return math_regions.tolist()

    # vote for the regions
    votes = vote_for_regions(math_regions, image, algorithm, thresh_votes)

    #cv2.imwrite('boundary_scores.png', boundary_scores)
    #math_region_labels = label_regions(math_regions, image)

    votes_regions = np.copy(votes)
    #math_regions = math_regions[math_regions[:, 4].argsort()]

    # TODO : Row info might be useful
    # use image to find the rows where all values are zero
    # use that info separate lines
    # so, that math regions on different lines do not get merged
    # This allows for horizontal merging, but skips vertical merging

    #blank_rows = find_blank_rows(image, 0)

    if projections == 1:
        votes[rows_with_at_least_k_black_pixels(image)] = 0

    # for blank rows, zero votes
    # for box in blank_rows:
    #    votes_regions[int(box[1]):int(box[3]), int(box[0]):int(box[2])] = 0
    #    image[int(box[1]):int(box[3]), int(box[0]):int(box[2])]=0
    # blank_rows = find_blank_rows_h(image)
    #
    # # for blank rows, zero votes
    # for row in blank_rows:
    #     votes_regions[row] = 0
    #     #image[row] = 0

    #votes[boundary_scores>50] = 0
    #cv2.imwrite('/home/psm2208/test.png', votes * 255)

    # this defines the connection filter
    # we allow any kind of connection
    # votes = votes.astype(np.uint8)
    #
    # contours, _ = cv2.findContours(votes, 1, 2)
    #
    # for cnt in contours:
    #     approx = cv2.approxPolyDP(cnt, 0.01 * cv2.arcLength(cnt, True), True)
    # #    print('len ', len(approx))
    #     if len(approx) >= 4:
    #         #print("rectangle")
    #         #cv2.drawContours(image, [cnt], 0, 255, -1)
    #         x, y, w, h = cv2.boundingRect(cnt)
    #         votes[y:y+h, x:x+w] = votes_regions[y:y+h, x:x+w]
    #cv2.imwrite("test.png", image)

    im_bw = convert_to_binary(image)

    structure = np.ones((3, 3), dtype=np.int)

    # find the rectangular regions
    # votes = ndimage.binary_opening(votes, structure=structure)

    labeled, ncomponents = label(votes, structure)

    # found the boxes. Now extract the co-ordinates left,top,right,bottom
    boxes = []
    indices = np.indices(votes.shape).T[:, :, [1, 0]]

    for i in range(ncomponents):

        labels = (labeled == (i+1))
        #labels = (labeled == i)
        pixels = indices[labels.T]

        if len(pixels) < 1:
            continue

        box = [min(pixels[:, 0]), min(pixels[:, 1]), max(pixels[:, 0]), max(pixels[:, 1])]

        # put all ones in bw image
        #cv2.imwrite("/home/psm2208/test.png", im_bw * 255)

        # expansion to correctly fit the region
        box = fit_box.adjust_box(im_bw, box)


        # if not np.all(votes[box[1]:box[3], box[0]:box[2]]):
        #
        #     ccs = np.unique(math_region_labels[box[1]:box[3], box[0]:box[2]])
        #
        #     # As the math regions are labels from low confidence to high confidence
        #     # the last region in ccs is the highest confident region.
        #     #TODO Need to apply NMS during this step
        #     # if 50% overlap reject the box
        #     # once NMS is done, do overlap-expand
        #     # if it is horizontal overlap, check if horizontal edge of larger rectangle
        #     # has more than 25% overlap then expand, otherwise do not expand
        #     # Finally do cc edge correction
        #     # Also, if horizontally very close merge the regions
        #     regions = []
        #     for cc in ccs:
        #         regions.append(math_regions[int(cc)])
        #
        #     regions = perform_nms(np.array(regions))
        #     boxes.extend(regions)
        #
        # else:
        #     boxes.append(box)
        boxes.append(box)

    return boxes


def convert_to_binary(image):

    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    im_bw = np.zeros(gray_image.shape)
    im_bw[gray_image > 127] = 0
    im_bw[gray_image <= 127] = 1

    return im_bw

def find_blank_rows_h(image):

    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    im_bw = np.zeros(gray_image.shape)
    im_bw[gray_image > 127] = 0
    im_bw[gray_image <= 127] = 1

    row_sum = np.sum(im_bw, axis=1)

    cum_sum = np.zeros(row_sum.shape)

    cum_sum[0] = row_sum[0]

    for i, sum in enumerate(row_sum[1:]):
        cum_sum[i+1] = cum_sum[i] + sum

    blank_rows = []
    for i, sum in enumerate(cum_sum):
        if is_blank(cum_sum, i):
            blank_rows.append(i)

    return blank_rows

# check n last rows
def is_blank(cum_sum, current, n=30, thresh=3000):

    # It is not a blank row
    ret = False

    # check above
    # if (current > 0) and ((cum_sum[current] - cum_sum[current-1]) == 0):
    #
    #     a_thresh = thresh
    #     if current < n:
    #         val = cum_sum[current]
    #         a_thresh = ((thresh/n) * (current + 1))
    #     else:
    #         val = cum_sum[current] - cum_sum[current-n]
    #
    #     # It is  a blank row
    #     if val >= a_thresh:
    #         ret = True

    # check below
    if (current < len(cum_sum)) and (cum_sum[current] - cum_sum[current-1]) == 0:

        b_thresh = thresh

        if current + n >= len(cum_sum):
            val = cum_sum[len(cum_sum)-1] - cum_sum[current]
            b_thresh = (thresh/n) * (len(cum_sum) - current)
        else:
            val = cum_sum[current + n] - cum_sum[current]

        # It is  a blank row
        if val >= b_thresh:
            ret = True

    return ret

def rows_with_at_least_k_black_pixels(image, k=10):

    im_bw = convert_to_binary(image) # characters are black
    rows = im_bw.sum(axis=1)
    return np.where(rows<=k)[0]


def find_blank_rows(image, line_spacing=1):

    gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blank_rows = np.all(gray_image == 255, axis=1)

    im_bw = np.zeros(gray_image.shape)
    im_bw[blank_rows] = 255
    #gray_image[~blank_rows] = 0

    #cv2.imwrite("/home/psm2208/code/eval/test.png", im_bw)

    labeled, ncomponents = ndimage.label(im_bw)
    rows = []

    indices = np.indices(im_bw.shape).T[:, :, [1, 0]]

    # for i in range(ncomponents):
    #
    #     labels = (labeled == (i+1))
    #     pixels = indices[labels.T]
    #
    #     box = [min(pixels[:, 0]), min(pixels[:, 1]), max(pixels[:, 0]), max(pixels[:, 1])]
    #
    #     if box[2] - box[0] > line_spacing:
    #         rows.append(box)

    line_bbs = ndimage.find_objects(labeled)
    sizes = np.array([[bb.stop - bb.start for bb in line_bb]
                      for line_bb in line_bbs])

    sizes = sizes[:,0]
    mask = (sizes > line_spacing)

    idx = np.flatnonzero(mask)

    for i in idx:
        labels = (labeled == (i+1))
        pixels = indices[labels.T]
        box = [min(pixels[:, 0]), min(pixels[:, 1]), max(pixels[:, 0]), max(pixels[:, 1])]
        rows.append(box)

    return rows

def perform_nms(math_regions):

    # convert from x1,y1,x2,y2 to x,y,w,h
    math_regions[:, 2] = math_regions[:, 2] - math_regions[:, 0]
    math_regions[:, 3] = math_regions[:, 3] - math_regions[:, 1]

    scores = math_regions[:, 4]
    math_regions = np.delete(math_regions, 4, 1)

    math_regions = math_regions.tolist()
    scores = scores.tolist()

    indices = NMSBoxes(math_regions, scores, 0.2, 0.5)

    indices = [item for sublist in indices for item in sublist]
    math_regions = [math_regions[i] for i in indices]

    math_regions = np.array(math_regions)

    # restore to x1,y1,x2,y2
    math_regions[:, 2] = math_regions[:, 2] + math_regions[:, 0]
    math_regions[:, 3] = math_regions[:, 3] + math_regions[:, 1]

    return math_regions.tolist()

def overlap_expand(math_regions):

    print('Number of math regions ', len(math_regions))

    if type(math_regions) != type([]):
        math_regions = math_regions.tolist()

    obsolete = []

    for i in range(len(math_regions)):
        for j in range(i+1, len(math_regions)):
            # print(i,j)
            if box_utils.intersects(math_regions[i], math_regions[j]):
                math_regions[i][0] = min(math_regions[i][0], math_regions[j][0])
                math_regions[i][1] = min(math_regions[i][1], math_regions[j][1])
                math_regions[i][2] = max(math_regions[i][2], math_regions[j][2])
                math_regions[i][3] = max(math_regions[i][3], math_regions[j][3])
                obsolete.append(j)

    math_regions = [i for j, i in enumerate(math_regions) if j not in obsolete]

    return math_regions


def stitch_patches(args):

    pdf_name, annotations_dir, output_dir, image_dir, gt_dir, char_annotations_dir, thresh = args

    print('Processing ', pdf_name)

    #annotations_dir = '/home/psm2208/data/GTDB/processed_annotations/',
    #output_dir = '/home/psm2208/code/eval/stitched_output'
    #image_dir = '/home/psm2208/data/GTDB/images/'

    # annotation map per pdf
    # map: {'name': {'1': []}}
    annotations_map = {}

    if pdf_name not in annotations_map:
        annotations_map[pdf_name] = {}

    for root, dirs, _ in os.walk(os.path.join(annotations_dir, pdf_name), topdown=False):

        for dir in dirs:
            for filename in os.listdir(os.path.join(annotations_dir, pdf_name, dir)):

                if filename.endswith(".csv") or filename.endswith(".pmath"):
                    patch_num = os.path.splitext(filename)[0]
                    page_num = os.path.basename(os.path.join(annotations_dir, pdf_name, dir))

                    if page_num not in annotations_map[pdf_name]:
                        annotations_map[pdf_name][page_num] = []

                    annotations_map[pdf_name][page_num].append(os.path.join(annotations_dir, pdf_name, dir, filename))

    char_annotations_map = {}
    if pdf_name not in char_annotations_map:
        char_annotations_map[pdf_name] = {}

    for filename in os.listdir(os.path.join(char_annotations_dir, pdf_name)):

        if filename.endswith(".csv") or filename.endswith(".pchar"):
            page_num = os.path.splitext(filename)[0]

            char_annotations_map[pdf_name][page_num] = \
                os.path.join(char_annotations_dir, pdf_name, filename)

    math_file = open(os.path.join(output_dir, pdf_name+'.csv'),'w')
    writer = csv.writer(math_file, delimiter=",")

    if not os.path.exists(os.path.join(output_dir, pdf_name)):
        os.mkdir(os.path.join(output_dir, pdf_name))


    for key in sorted(annotations_map[pdf_name]):

        if key not in char_annotations_map[pdf_name]:
            char_annotations_map[pdf_name][key] = ""

        # basically it is called for each page in the pdf
        math_regions = combine_math_regions(
                        pdf_name,
                        key,
                        annotations_map[pdf_name][key],
                        char_annotations_map[pdf_name][key],
                        os.path.join(image_dir, pdf_name, key + '.png'),
                        os.path.join(output_dir, pdf_name, key + '.png'),
                        gt_dir,
                        thresh,
                        output_dir)

        for math_region in math_regions:
            math_region.insert(0,int(key)-1)
            writer.writerow(math_region)

    math_file.close()


def patch_stitch(filename, annotations_dir, output_dir, image_dir='/home/psm2208/data/GTDB/images/',
                 gt_dir="/home/psm2208/data/GTDB/", char_gt="", thresh=20):

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)

    if not os.path.exists(output_dir):
        os.mkdir(output_dir)

    training_pdf_names_list = []
    training_pdf_names = open(filename, 'r')

    for pdf_name in training_pdf_names:
        pdf_name = pdf_name.strip()

        if pdf_name != '':
            training_pdf_names_list.append((pdf_name, annotations_dir, output_dir, image_dir, gt_dir, char_gt, thresh))

    training_pdf_names.close()

    pool = Pool(processes=1)
    pool.map(stitch_patches, training_pdf_names_list)
    pool.close()
    pool.join()


def fusion_stitch_grid(filename, annotations_dir, output_dir,
                       image_dir='/home/psm2208/data/GTDB/images/',
                       gt_dir="/home/psm2208/data/GTDB/", char_gt="", thresh=20):

    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)

    if not os.path.exists(output_dir):
        os.mkdir(output_dir)

    pages_list = []
    pdf_names = open(filename, 'r')

    annotations_map = {}
    char_annotations_map = {}

    for pdf_name in pdf_names:
        pdf_name = pdf_name.strip()

        if pdf_name != '':

            if pdf_name not in annotations_map:
                annotations_map[pdf_name] = {}

            for root, dirs, _ in os.walk(os.path.join(annotations_dir, pdf_name), topdown=False):

                for dir in dirs:
                    for filename in os.listdir(os.path.join(annotations_dir, pdf_name, dir)):

                        if filename.endswith(".csv") or filename.endswith(".pmath"):
                            patch_num = os.path.splitext(filename)[0]
                            page_num = os.path.basename(os.path.join(annotations_dir, pdf_name, dir))

                            if page_num not in annotations_map[pdf_name]:
                                annotations_map[pdf_name][page_num] = []

                            annotations_map[pdf_name][page_num].append(
                                os.path.join(annotations_dir, pdf_name, dir, filename))


            if pdf_name not in char_annotations_map:
                char_annotations_map[pdf_name] = {}

            for filename in os.listdir(os.path.join(char_gt, pdf_name)):

                if filename.endswith(".csv") or filename.endswith(".pchar"):
                    page_num = os.path.splitext(filename)[0]

                    char_annotations_map[pdf_name][page_num] = \
                        os.path.join(char_gt, pdf_name, filename)

            for root, dirs, files in os.walk(os.path.join(char_gt, pdf_name)):
                for name in files:
                    if name.endswith(".pchar"):
                        page_num = os.path.splitext(name)[0]
                        if page_num in annotations_map[pdf_name]:
                            image = cv2.imread(os.path.join(image_dir, pdf_name, page_num + '.png'))
                            pages_list.append((image,pdf_name,page_num,annotations_map[pdf_name][page_num]))

    pdf_names.close()

    # find math regions
    pool = Pool(processes=32)
    total = str(len(pages_list))
    math_cache = pool.map(read_math_regions, pages_list)

    pool.close()
    pool.join()


    # find intersecting math regions
    pool = Pool(processes=32)
    inter_math = pool.map(box_utils.find_intersecting_boxes, math_cache)

    pool.close()
    pool.join()

    fusion_list = []

    for i, page in enumerate(pages_list):
        pdf_name = page[1]
        page_num = page[2]
        for a in np.arange(0.3, 1.1, 0.1):
            for b in np.arange(0.0, 1.1, 0.1):
                for c in np.arange(0.0, 1.1, 0.1):
                    fusion_list.append((pdf_name,
                                        page_num,
                                        output_dir,
                                        inter_math[i],
                                        math_cache[i],
                                        a,b,c))

    pool = Pool(processes=32)
    total = str(len(fusion_list))
    #pool.map(fusion, fusion_list)
    start = time.time()
    init = start

    for i, _ in enumerate(pool.imap_unordered(fusion, fusion_list), 1):
         print('\nprogress: ' + str(i) + '/' + total)
         if i%100==0:
             current = time.time()
             print('\nTime taken for last 100, total time:', current-start, current-init)
             start = time.time()

    pool.close()
    pool.join()


if __name__ == '__main__':
    #stitch_patches("TMJ_1990_163_193")
    #stitch_patches("AIF_1970_493_498", "/home/psm2208/code/eval")
    #filename = sys.argv[1] # train_pdf

    #stitch_patches(("Arkiv_1997_185_199", "/home/psm2208/code/eval/Train_Focal_100",
    #             "/home/psm2208/code/eval/Train_Focal_100/out", '/home/psm2208/data/GTDB/images/'))

    #patch_stitch(filename, sys.argv[2], sys.argv[3])
    stride = 0.1

    #stitch_patches(("InvM_1999_163_181", "/home/psm2208/code/eval/Train_Focal_10_25",
    #                "/home/psm2208/code/eval/Train_Focal_10_25/voting_equal_rows",
    #                '/home/psm2208/data/GTDB/images/'))

    thresh = float(sys.argv[1]) # 30
    algorithm = sys.argv[2] # equal
    type = sys.argv[3]  # train_pdf
    dir_to_eval = sys.argv[4] # Test3_Focal_10_25

    if len(sys.argv) > 5:
        if_visualize = int(sys.argv[5])  # visualize
        projections = int(sys.argv[6])  # projections
    else:
        visualize = 0
        projections = 0

    final_width = 512
    final_height = 512

    home_data = "/home/psm2208/data/GTDB/"
    home_eval = "/home/psm2208/code/eval/"
    home_images = "/home/psm2208/data/GTDB/images/"
    home_anno = "/home/psm2208/data/GTDB/annotations/"
    home_char = "/home/psm2208/data/GTDB/char_annotations/"

    # patch_stitch(home_data + type, home_eval + dir_to_eval,
    #              home_eval + dir_to_eval + "/" + algorithm + "_" + str(thresh),
    #              home_images, home_anno, home_char, thresh)

    fusion_stitch_grid(home_data + type, home_eval + dir_to_eval,
                       home_eval + dir_to_eval + "/" + algorithm + "_" + str(thresh),
                       home_images, home_anno, home_char, thresh)

    # patch_stitch("/home/psm2208/data/GTDB/test_pdf", "/home/psm2208/code/eval/Test_char_Focal_10_25",
    #              "/home/psm2208/code/eval/Test_char_Focal_10_25/voting_equal_" + str(thresh),
    #              '/home/psm2208/data/GTDB/images/', "/home/psm2208/data/GTDB/annotations/", thresh)
